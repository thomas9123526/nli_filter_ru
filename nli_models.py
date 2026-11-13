#!/usr/bin/env python3
"""
nli_models.py - load and run the zero-shot NLI models in ./models.

A small, reusable library plus a command line tool.

Models (folders under ./models, or --models-root / $NLI_MODELS_ROOT):
    modernbert  ModernBERT-large-zeroshot-v2.0   fast, English, 8k context
    deberta     deberta-v3-large-zeroshot-v2.0   most accurate, English, 512 tokens
    bge-m3      bge-m3-zeroshot-v2.0             multilingual, 8k context
A folder path or a Hugging Face ID also works.

Library use
-----------
    from nli_models import NLIModel, NLIPool, iter_records

    # one model on one device, synchronous
    model = NLIModel("modernbert", device="cpu")
    model.entailment("Moscow is the capital of Russia.", "This text is about Russia.")   # -> 0.98
    model.score_pairs(premises, hypotheses)          # list of entailment probabilities
    model.classify(texts, ["film", "song"], template="This text is about a Russian {}.")

    # one or more devices, run modes: "single" | "thread" | "process"
    with NLIPool("modernbert", devices="cuda:0,cuda:1", mode="process") as pool:
        future = pool.submit(premises, hypotheses)   # non-blocking, concurrent.futures.Future
        scores = pool.score(premises, hypotheses)    # blocking

    # read .jsonl / .json / .gz / .zst / .zip / .rar / .parquet / .arrow files, folders and globs
    for rec in iter_records(["data/", "more/*.jsonl.zst"]):
        rec.source, rec.line, rec.data["text"]

Command line
------------
    python nli_models.py --list-models
    python nli_models.py --check all --device cpu
    python nli_models.py --model modernbert --text "Moscow is cold." --hypothesis "This text is about Russia."
    python nli_models.py --model deberta --input data/ --labels "film,song,history" \
        --template "This text is about a Russian {}." --out scores.jsonl.zst
    python nli_models.py --model modernbert --input "shards/*.zst" --hypothesis "This text is about Russia." \
        --device cuda --mode process --batch-size 64 --out scores.jsonl.zst

Every probability returned is P(entailment) from a softmax over the model's classes.
Optional packages: orjson (faster JSON), zstandard (.zst; Python 3.14+ has it built in).
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import glob
import gzip
import inspect
import io
import itertools
import json
import logging
import os
import queue
import re
import sys
import threading
import time
import traceback
import zipfile
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Callable, Dict, Iterator, List, Optional, Sequence, Tuple, Union

try:
    import orjson
except ImportError:  # pragma: no cover
    orjson = None

try:
    import zstandard
except ImportError:  # pragma: no cover
    zstandard = None

__version__ = "1.0.0"
__all__ = [
    "ModelSpec", "MODEL_SPECS", "ModelRegistry", "NLIModel", "NLIPool",
    "Record", "JsonlSource", "expand_inputs", "iter_sources", "iter_records",
    "AtomicOutput", "open_output", "json_loads", "json_dumps",
    "resolve_device", "resolve_devices", "resolve_dtype", "plan_batches", "zstd_available", "quiet_transformers",
]

log = logging.getLogger("nli_models")

PathLike = Union[str, os.PathLike]

# --------------------------------------------------------------------------------------------------
# JSON helpers
# --------------------------------------------------------------------------------------------------


def json_loads(data: Union[bytes, str]) -> Any:
    """Parse JSON (orjson when installed)."""
    if orjson is not None:
        return orjson.loads(data)
    return json.loads(data)


def json_dumps(obj: Any) -> str:
    """One-line JSON string, non-ASCII kept as is (orjson when installed)."""
    if orjson is not None:
        return orjson.dumps(obj).decode("utf-8")
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


# --------------------------------------------------------------------------------------------------
# Model registry
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelSpec:
    key: str
    folder: str
    hf_id: str
    max_length: int                     # longest pair (premise + hypothesis) the model accepts, in tokens
    attn_implementation: Optional[str]  # attention kernel to request from transformers
    languages: str
    role: str
    aliases: Tuple[str, ...] = ()


MODEL_SPECS: Dict[str, ModelSpec] = {
    "modernbert": ModelSpec(
        "modernbert", "ModernBERT-large-zeroshot-v2.0", "MoritzLaurer/ModernBERT-large-zeroshot-v2.0",
        8192, "sdpa", "English", "fast: scores every candidate",
        ("modernbert-large", "modernbert-large-zeroshot-v2.0", "fast")),
    "deberta": ModelSpec(
        "deberta", "deberta-v3-large-zeroshot-v2.0", "MoritzLaurer/deberta-v3-large-zeroshot-v2.0",
        512, "eager", "English", "accurate: judge for uncertain scores",
        ("deberta-v3-large", "deberta-v3-large-zeroshot-v2.0", "judge", "accurate")),
    "bge-m3": ModelSpec(
        "bge-m3", "bge-m3-zeroshot-v2.0", "MoritzLaurer/bge-m3-zeroshot-v2.0",
        8192, "sdpa", "100+ languages", "multilingual fallback",
        ("bge", "bgem3", "bge-m3-zeroshot-v2.0", "multilingual")),
}


class ModelRegistry:
    """Maps a model name, alias, folder path or Hugging Face ID to a loadable location."""

    def __init__(self, models_root: Optional[PathLike] = None):
        root = models_root or os.environ.get("NLI_MODELS_ROOT") or Path(__file__).resolve().parent / "models"
        self.models_root = Path(root)

    @staticmethod
    def spec(name: str) -> Optional[ModelSpec]:
        """Spec for a key, alias, folder name or HF ID (case-insensitive); None if unknown."""
        n = str(name).strip().lower().rstrip("/\\")
        n_base = n.replace("\\", "/").split("/")[-1]
        for spec in MODEL_SPECS.values():
            names = {spec.key, spec.folder.lower(), spec.hf_id.lower(), *spec.aliases}
            if n in names or n_base in names:
                return spec
        return None

    def resolve(self, name_or_path: PathLike) -> Tuple[str, Optional[ModelSpec]]:
        """Return (location for from_pretrained, spec or None). Raises FileNotFoundError / ValueError."""
        p = Path(name_or_path)
        if p.is_dir():
            return str(p), self.spec(p.name)
        spec = self.spec(str(name_or_path))
        if spec is not None:
            for candidate in (self.models_root / spec.folder, self.models_root / spec.key):
                if (candidate / "config.json").is_file():
                    return str(candidate), spec
            raise FileNotFoundError(
                f"model '{name_or_path}' not found under {self.models_root} (expected folder "
                f"'{spec.folder}'); pass --models-root / models_root=, set NLI_MODELS_ROOT, or give the folder path")
        if "/" in str(name_or_path):  # looks like a Hugging Face ID: let transformers find it (cache / hub)
            return str(name_or_path), None
        raise ValueError(f"unknown model '{name_or_path}'; known: {', '.join(MODEL_SPECS)} or a folder path")

    def available(self) -> List[Tuple[ModelSpec, Path, bool]]:
        """(spec, expected folder, folder exists) for every known model."""
        out = []
        for spec in MODEL_SPECS.values():
            folder = self.models_root / spec.folder
            out.append((spec, folder, (folder / "config.json").is_file()))
        return out


# --------------------------------------------------------------------------------------------------
# Devices, dtypes, batching
# --------------------------------------------------------------------------------------------------

_DTYPE_NAMES = {
    "bf16": "bfloat16", "bfloat16": "bfloat16",
    "fp16": "float16", "float16": "float16", "half": "float16",
    "fp32": "float32", "float32": "float32", "float": "float32",
}


def _torch():
    try:
        import torch
    except ImportError as exc:  # pragma: no cover
        raise ImportError("PyTorch is required for the NLI models: pip install torch") from exc
    return torch


def resolve_devices(devices: Union[str, Sequence[str], None] = "auto") -> List[str]:
    """
    "auto"  -> every CUDA GPU, else ["cpu"]
    "cuda"  -> every CUDA GPU          "cpu" -> ["cpu"]
    "cuda:0,cuda:1" or "0,1" or ["cuda:0", "cuda:1"] -> that list
    "cpu*4" -> ["cpu"] * 4 (several CPU workers; useful with mode="process")
    """
    if devices is None:
        devices = "auto"
    if isinstance(devices, str):
        text = devices.strip().lower()
        if "*" in text:
            dev, _, count = text.partition("*")
            return [resolve_device(dev)] * int(count)
        if text in ("auto", "cuda", "gpu"):
            torch = _torch()
            n = torch.cuda.device_count() if torch.cuda.is_available() else 0
            if n:
                return [f"cuda:{i}" for i in range(n)]
            if text != "auto":
                raise RuntimeError("CUDA requested but torch.cuda.is_available() is False")
            return ["cpu"]
        items = [d.strip() for d in text.split(",") if d.strip()]
    else:
        items = [str(d).strip().lower() for d in devices]
    return [resolve_device(d) for d in items]


def resolve_device(device: Optional[str] = "auto") -> str:
    """One device string: "auto" -> "cuda:0" if available else "cpu"; "1" -> "cuda:1"; "cuda" -> "cuda:0"."""
    d = (device or "auto").strip().lower()
    if d == "auto":
        torch = _torch()
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    if d.isdigit():
        return f"cuda:{d}"
    if d in ("cuda", "gpu"):
        return "cuda:0"
    return d


def resolve_dtype(dtype: Optional[str], device: str):
    """"auto" -> bfloat16 on GPUs that support it, float16 on other GPUs, float32 on CPU."""
    torch = _torch()
    d = (dtype or "auto").lower()
    if d == "auto":
        if device.startswith("cuda"):
            idx = int(device.split(":")[1]) if ":" in device else 0
            major, _ = torch.cuda.get_device_capability(idx)
            return torch.bfloat16 if major >= 8 else torch.float16
        return torch.float32
    if d not in _DTYPE_NAMES:
        raise ValueError(f"unknown dtype '{dtype}' (use auto, bf16, fp16, fp32)")
    return getattr(torch, _DTYPE_NAMES[d])


def plan_batches(lengths: Sequence[int], batch_size: int = 32, max_batch_tokens: Optional[int] = None,
                 chars_per_token: float = 4.0, max_length: int = 512) -> List[List[int]]:
    """
    Group item indices into batches, longest first (less padding, out-of-memory shows up at once).
    lengths are character counts; a batch closes at batch_size items or when
    (longest item in tokens) x (items) would exceed max_batch_tokens.
    """
    order = sorted(range(len(lengths)), key=lambda i: -lengths[i])
    batches: List[List[int]] = []
    cur: List[int] = []
    cur_max = 0.0
    for i in order:
        est = min(float(max_length), lengths[i] / chars_per_token + 4)
        new_max = max(cur_max, est)
        if cur and (len(cur) >= batch_size or (max_batch_tokens and new_max * (len(cur) + 1) > max_batch_tokens)):
            batches.append(cur)
            cur, new_max = [], est
        cur.append(i)
        cur_max = new_max
    if cur:
        batches.append(cur)
    return batches


def _broadcast(premises: Sequence[str], hypotheses: Union[str, Sequence[str]]) -> List[str]:
    if isinstance(hypotheses, str):
        return [hypotheses] * len(premises)
    if len(hypotheses) != len(premises):
        raise ValueError(f"{len(premises)} premises but {len(hypotheses)} hypotheses")
    return list(hypotheses)


def _classify(score_fn: Callable[[List[str], List[str]], List[float]], texts: Sequence[str],
              labels: Sequence[str], template: str = "{}", multi_label: bool = True) -> List[Dict[str, float]]:
    """Shared by NLIModel.classify and NLIPool.classify."""
    if not labels:
        raise ValueError("no labels")
    hyps = [template.format(label) if "{}" in template else f"{template} {label}" for label in labels]
    premises = [t for t in texts for _ in hyps]
    scores = score_fn(premises, hyps * len(texts))
    out = []
    for i in range(len(texts)):
        row = scores[i * len(labels):(i + 1) * len(labels)]
        if not multi_label:  # one label per text: normalise the entailment probabilities to sum 1
            total = sum(row) or 1.0
            row = [s / total for s in row]
        out.append(dict(zip(labels, row)))
    return out


# --------------------------------------------------------------------------------------------------
# One model on one device
# --------------------------------------------------------------------------------------------------


class NLIModel:
    """
    One zero-shot NLI model on one device. Thread-safe for scoring (inference only).

        model = NLIModel("modernbert", device="cuda:0", dtype="bf16", max_length=512)
        model.score_pairs(["Moscow is cold."], ["This text is about Russia."])  -> [0.97]
    """

    def __init__(self, model: PathLike = "modernbert", device: str = "auto", dtype: str = "auto",
                 max_length: Optional[int] = None, models_root: Optional[PathLike] = None,
                 attn_implementation: Optional[str] = "auto", compile: bool = False,
                 cpu_threads: Optional[int] = None, batch_size: int = 32,
                 max_batch_tokens: Optional[int] = None, local_files_only: bool = True):
        torch = _torch()
        import transformers
        from transformers import AutoConfig, AutoModelForSequenceClassification, AutoTokenizer

        t0 = time.perf_counter()
        self.path, self.spec = ModelRegistry(models_root).resolve(model)
        self.name = self.spec.key if self.spec else Path(self.path).name
        self.device = resolve_device(device)
        self.dtype = resolve_dtype(dtype, self.device)
        self.batch_size = int(batch_size)
        self.max_batch_tokens = max_batch_tokens
        if cpu_threads:  # torch CPU threads of this process (on GPU only used for small helper ops)
            torch.set_num_threads(int(cpu_threads))

        self.tokenizer = AutoTokenizer.from_pretrained(self.path, local_files_only=local_files_only)
        config = AutoConfig.from_pretrained(self.path, local_files_only=local_files_only)

        kwargs: Dict[str, Any] = {"local_files_only": local_files_only}
        tf_version = tuple(int(x) for x in transformers.__version__.split(".")[:2] if x.isdigit())
        kwargs["dtype" if tf_version >= (4, 56) else "torch_dtype"] = self.dtype
        attn = self.spec.attn_implementation if (attn_implementation == "auto" and self.spec) else attn_implementation
        if attn and attn != "auto":
            kwargs["attn_implementation"] = attn
        if getattr(config, "model_type", "") == "modernbert" and not compile:
            kwargs["reference_compile"] = False  # no torch.compile (needs triton; slow first batch)
        try:
            net = AutoModelForSequenceClassification.from_pretrained(self.path, **kwargs)
        except (ValueError, ImportError) as exc:
            if "attn_implementation" not in kwargs:
                raise
            log.warning("%s: attention '%s' not available (%s); using the default", self.name, attn, exc)
            kwargs.pop("attn_implementation")
            net = AutoModelForSequenceClassification.from_pretrained(self.path, **kwargs)
        self.model = net.to(self.device).eval()
        if compile:
            self.model = torch.compile(self.model)

        id2label = {int(k): str(v) for k, v in self.model.config.id2label.items()}
        entail = [i for i, lab in id2label.items() if lab.lower().startswith("entail")]
        if len(entail) != 1:
            raise ValueError(f"{self.name}: cannot find the entailment class in id2label={id2label}")
        self.entail_index = entail[0]
        self.labels = id2label

        limit = self.spec.max_length if self.spec else int(getattr(config, "max_position_embeddings", 512))
        tok_max = getattr(self.tokenizer, "model_max_length", None)
        if isinstance(tok_max, int) and 0 < tok_max < 1_000_000:
            limit = min(limit, tok_max)
        self.max_length = min(int(max_length), limit) if max_length else min(512, limit)
        accepted = set(inspect.signature(self.model.forward).parameters)
        self._input_keys = [k for k in ("input_ids", "attention_mask", "token_type_ids") if k in accepted]
        self.load_seconds = time.perf_counter() - t0
        log.info("loaded %s on %s (%s, max_length %d) in %.1fs",
                 self.name, self.device, str(self.dtype).replace("torch.", ""), self.max_length, self.load_seconds)

    # ---- scoring --------------------------------------------------------------------------------

    def score_batch(self, premises: Sequence[str], hypotheses: Sequence[str]) -> List[float]:
        """Score one batch as given (no re-ordering). Halves the batch and retries on CUDA out-of-memory."""
        torch = _torch()
        try:
            return self._forward(premises, hypotheses)
        except torch.cuda.OutOfMemoryError:
            if len(premises) <= 1:
                raise
            torch.cuda.empty_cache()
            mid = len(premises) // 2
            log.warning("%s on %s: out of memory with %d pairs, splitting", self.name, self.device, len(premises))
            return (self.score_batch(premises[:mid], hypotheses[:mid])
                    + self.score_batch(premises[mid:], hypotheses[mid:]))

    def _forward(self, premises: Sequence[str], hypotheses: Sequence[str]) -> List[float]:
        torch = _torch()
        premises = [p if isinstance(p, str) else str(p) for p in premises]
        try:
            enc = self.tokenizer(premises, list(hypotheses), truncation="only_first", max_length=self.max_length,
                                 padding=True, return_tensors="pt")
        except Exception:  # hypothesis alone longer than max_length
            enc = self.tokenizer(premises, list(hypotheses), truncation=True, max_length=self.max_length,
                                 padding=True, return_tensors="pt")
        inputs = {k: enc[k].to(self.device) for k in self._input_keys if k in enc}
        with torch.inference_mode():
            logits = self.model(**inputs).logits.float()
        return logits.softmax(-1)[:, self.entail_index].cpu().tolist()

    def score_pairs(self, premises: Sequence[str], hypotheses: Union[str, Sequence[str]],
                    batch_size: Optional[int] = None, max_batch_tokens: Optional[int] = None) -> List[float]:
        """P(entailment) for every (premise, hypothesis) pair, in input order. hypotheses may be one string."""
        hyps = _broadcast(premises, hypotheses)
        scores: List[float] = [0.0] * len(premises)
        lengths = [len(p) + len(h) for p, h in zip(premises, hyps)]
        for idx in plan_batches(lengths, batch_size or self.batch_size, max_batch_tokens or self.max_batch_tokens,
                                max_length=self.max_length):
            for i, s in zip(idx, self.score_batch([premises[i] for i in idx], [hyps[i] for i in idx])):
                scores[i] = s
        return scores

    def entailment(self, premise: str, hypothesis: str) -> float:
        """P(entailment) for one pair."""
        return self.score_batch([premise], [hypothesis])[0]

    def classify(self, texts: Union[str, Sequence[str]], labels: Sequence[str], template: str = "{}",
                 multi_label: bool = True) -> Union[Dict[str, float], List[Dict[str, float]]]:
        """
        Zero-shot classification. template turns a label into a hypothesis, e.g. "This text is about {}.".
        multi_label=True: independent probability per label; False: scores normalised to sum 1 per text.
        """
        single = isinstance(texts, str)
        out = _classify(self.score_pairs, [texts] if single else list(texts), labels, template, multi_label)
        return out[0] if single else out

    def info(self) -> Dict[str, Any]:
        return {"model": self.name, "path": self.path, "device": self.device,
                "dtype": str(self.dtype).replace("torch.", ""), "max_length": self.max_length,
                "entailment_label": self.labels[self.entail_index], "load_seconds": round(self.load_seconds, 2)}

    def release(self) -> None:
        """Free the weights (and GPU memory)."""
        torch = _torch()
        self.model = None
        if self.device.startswith("cuda"):
            torch.cuda.empty_cache()

    def __repr__(self) -> str:
        return f"NLIModel({self.name!r}, device={self.device!r}, dtype={str(self.dtype).replace('torch.', '')!r})"


# --------------------------------------------------------------------------------------------------
# Several devices / workers
# --------------------------------------------------------------------------------------------------


class _Job:
    __slots__ = ("future", "scores", "remaining", "lock")

    def __init__(self, future: Future, n: int, parts: int):
        self.future = future
        self.scores: List[Optional[float]] = [None] * n
        self.remaining = parts
        self.lock = threading.Lock()


def quiet_transformers() -> None:
    """Hide transformers' weight-loading progress bars and info messages."""
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    with contextlib.suppress(Exception):
        from transformers.utils import logging as tf_logging
        tf_logging.set_verbosity_error()
        tf_logging.disable_progress_bar()


def _process_worker(wid: int, device: str, model_kwargs: Dict[str, Any], task_q, result_q,
                    log_level: int) -> None:
    """Runs in a child process: load the model once, then score batches until a None arrives."""
    if device.startswith("cuda"):
        # A GPU worker needs few CPU threads. Without a cap every worker (16 on 8 GPUs with a judge) starts
        # torch, OpenMP and tokenizer thread pools as large as the machine, and they fight over the cores.
        # Set before torch / tokenizers are imported in this process.
        n = str(model_kwargs.get("cpu_threads") or 4)
        for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "RAYON_NUM_THREADS"):
            os.environ.setdefault(var, n)
    logging.basicConfig(level=log_level, format=f"%(asctime)s [worker {wid} {device}] %(message)s", stream=sys.stderr)
    if log_level > logging.INFO:
        quiet_transformers()
    try:
        model = NLIModel(device=device, **model_kwargs)
    except BaseException:
        result_q.put(("error", wid, traceback.format_exc()))
        return
    result_q.put(("ready", wid, model.info()))
    while True:
        task = task_q.get()
        if task is None:
            break
        tid, premises, hyps = task
        try:
            result_q.put(("ok", tid, model.score_batch(premises, hyps)))
        except BaseException:
            result_q.put(("fail", tid, traceback.format_exc()))


class NLIPool:
    """
    Run one model on one or more devices.

    mode
        "single"   no extra threads; submit() scores in the calling thread (tests, debugging)
        "thread"   one worker thread per (device x workers_per_device); threads on the same
                   device share one copy of the model; low memory, good for 1-4 GPUs
        "process"  one child process per (device x workers_per_device), each with its own model;
                   no GIL contention, best for 8 GPUs or several CPU workers ("cpu*4")
        "auto"     "single" for one device, else "thread"

    submit(premises, hypotheses) -> Future[list[float]] can be called from many threads at once;
    each request is split into length-sorted batches that all workers share.
    """

    MODES = ("auto", "single", "thread", "process")

    def __init__(self, model: PathLike = "modernbert", devices: Union[str, Sequence[str], None] = "auto",
                 mode: str = "auto", workers_per_device: int = 1, batch_size: int = 32,
                 max_batch_tokens: Optional[int] = None, dtype: str = "auto", max_length: Optional[int] = None,
                 models_root: Optional[PathLike] = None, attn_implementation: Optional[str] = "auto",
                 compile: bool = False, cpu_threads: Optional[int] = None, start_timeout: float = 1800.0):
        if mode not in self.MODES:
            raise ValueError(f"mode must be one of {self.MODES}")
        self.devices = resolve_devices(devices)
        slots = [d for d in self.devices for _ in range(max(1, int(workers_per_device)))]
        if mode == "auto":
            mode = "single" if len(slots) == 1 else "thread"
        self.mode = mode
        self.batch_size = int(batch_size)
        self.max_batch_tokens = max_batch_tokens
        self.model_kwargs = dict(model=str(model), dtype=dtype, max_length=max_length, models_root=models_root,
                                 attn_implementation=attn_implementation, compile=compile, cpu_threads=cpu_threads,
                                 batch_size=batch_size, max_batch_tokens=max_batch_tokens)
        self._lock = threading.Lock()
        self._tasks: Dict[int, Tuple[_Job, List[int]]] = {}
        self._task_ids = itertools.count()
        self._closed = False
        self._pairs = 0
        self._batches = 0
        self._threads: List[threading.Thread] = []
        self._procs: List[Any] = []
        self.worker_info: List[Dict[str, Any]] = []
        self.max_length = 512
        self.name = str(model)

        if mode == "single":
            if len(slots) > 1:
                log.warning("mode 'single' uses only the first device (%s)", slots[0])
            self._model = NLIModel(device=slots[0], **self.model_kwargs)
            self._set_meta(self._model.info())
        elif mode == "thread":
            self._task_q: Any = queue.Queue()
            models: Dict[str, NLIModel] = {}
            for dev in slots:
                if dev not in models:
                    models[dev] = NLIModel(device=dev, **self.model_kwargs)
                    self._set_meta(models[dev].info())
            for i, dev in enumerate(slots):
                t = threading.Thread(target=self._thread_worker, args=(models[dev],), daemon=True,
                                     name=f"nli-{models[dev].name}-{dev}-{i}")
                t.start()
                self._threads.append(t)
        else:
            self._start_processes(slots, start_timeout)

    # ---- set-up ---------------------------------------------------------------------------------

    def _set_meta(self, info: Dict[str, Any]) -> None:
        self.worker_info.append(info)
        self.max_length = info["max_length"]
        self.name = info["model"]

    def _start_processes(self, slots: List[str], start_timeout: float) -> None:
        import multiprocessing as mp
        ctx = mp.get_context("spawn")  # CUDA needs spawn; same behaviour on Linux and Windows
        self._task_q = ctx.Queue()
        self._result_q = ctx.Queue()
        for wid, dev in enumerate(slots):
            p = ctx.Process(target=_process_worker, daemon=True, name=f"nli-worker-{wid}",
                            args=(wid, dev, self.model_kwargs, self._task_q, self._result_q, log.getEffectiveLevel()))
            p.start()
            self._procs.append(p)
        ready, deadline = 0, time.monotonic() + start_timeout
        while ready < len(slots):
            try:
                msg = self._result_q.get(timeout=1.0)
            except queue.Empty:
                if time.monotonic() > deadline or any(not p.is_alive() for p in self._procs):
                    self._terminate()
                    raise RuntimeError("NLI worker process did not start (died or timed out)")
                continue
            if msg[0] == "error":
                self._terminate()
                raise RuntimeError(f"NLI worker {msg[1]} failed to load the model:\n{msg[2]}")
            if msg[0] == "ready":
                ready += 1
                self._set_meta(msg[2])
        self._collector = threading.Thread(target=self._collect, daemon=True, name="nli-collector")
        self._collector.start()

    # ---- workers --------------------------------------------------------------------------------

    def _thread_worker(self, model: NLIModel) -> None:
        while True:
            task = self._task_q.get()
            if task is None:
                return
            tid, premises, hyps = task
            try:
                self._complete(tid, model.score_batch(premises, hyps), None)
            except BaseException as exc:
                self._complete(tid, None, exc)

    def _collect(self) -> None:
        while True:
            try:
                msg = self._result_q.get(timeout=1.0)
            except queue.Empty:
                if self._closed:
                    return
                if any(not p.is_alive() for p in self._procs):
                    self._fail_all(RuntimeError("an NLI worker process died (out of memory?)"))
                    return
                continue
            except (EOFError, OSError):
                return
            kind = msg[0]
            if kind == "ok":
                self._complete(msg[1], msg[2], None)
            elif kind == "fail":
                self._complete(msg[1], None, RuntimeError(f"NLI worker error:\n{msg[2]}"))

    def _complete(self, tid: int, scores: Optional[List[float]], error: Optional[BaseException]) -> None:
        with self._lock:
            entry = self._tasks.pop(tid, None)
            if entry is not None and scores is not None:
                self._pairs += len(scores)
                self._batches += 1
        if entry is None:
            return
        job, idx = entry
        if error is not None:
            with contextlib.suppress(Exception):
                job.future.set_exception(error)
            return
        for i, s in zip(idx, scores):
            job.scores[i] = s
        with job.lock:
            job.remaining -= 1
            done = job.remaining == 0
        if done and not job.future.done():
            with contextlib.suppress(Exception):
                job.future.set_result(job.scores)

    def _fail_all(self, error: BaseException) -> None:
        with self._lock:
            entries = list(self._tasks.values())
            self._tasks.clear()
        for job, _ in entries:
            with contextlib.suppress(Exception):
                job.future.set_exception(error)

    # ---- public API -----------------------------------------------------------------------------

    def submit(self, premises: Sequence[str], hypotheses: Union[str, Sequence[str]]) -> Future:
        """Queue pairs for scoring; returns a Future whose result is the list of P(entailment), in order."""
        if self._closed:
            raise RuntimeError("pool is closed")
        premises = list(premises)
        hyps = _broadcast(premises, hypotheses)
        fut: Future = Future()
        if not premises:
            fut.set_result([])
            return fut
        if self.mode == "single":
            try:
                result = self._model.score_pairs(premises, hyps)
                with self._lock:
                    self._pairs += len(result)
                fut.set_result(result)
            except BaseException as exc:
                fut.set_exception(exc)
            return fut
        lengths = [len(p) + len(h) for p, h in zip(premises, hyps)]
        batches = plan_batches(lengths, self.batch_size, self.max_batch_tokens, max_length=self.max_length)
        job = _Job(fut, len(premises), len(batches))
        for idx in batches:
            tid = next(self._task_ids)
            with self._lock:
                self._tasks[tid] = (job, idx)
            self._task_q.put((tid, [premises[i] for i in idx], [hyps[i] for i in idx]))
        return fut

    def score(self, premises: Sequence[str], hypotheses: Union[str, Sequence[str]],
              timeout: Optional[float] = None) -> List[float]:
        """Blocking version of submit()."""
        return self.submit(premises, hypotheses).result(timeout)

    def classify(self, texts: Union[str, Sequence[str]], labels: Sequence[str], template: str = "{}",
                 multi_label: bool = True) -> Union[Dict[str, float], List[Dict[str, float]]]:
        """Same as NLIModel.classify, spread over the pool."""
        single = isinstance(texts, str)
        out = _classify(self.score, [texts] if single else list(texts), labels, template, multi_label)
        return out[0] if single else out

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"pairs": self._pairs, "batches": self._batches, "pending_batches": len(self._tasks)}

    def info(self) -> Dict[str, Any]:
        return {"model": self.name, "mode": self.mode, "devices": self.devices, "workers": max(1, len(self.worker_info)
                if self.mode == "process" else len(self._threads) or 1), "max_length": self.max_length,
                "batch_size": self.batch_size, "max_batch_tokens": self.max_batch_tokens,
                "dtype": self.worker_info[0]["dtype"] if self.worker_info else None,
                "load_seconds": max((w["load_seconds"] for w in self.worker_info), default=0.0)}

    def close(self) -> None:
        """Stop the workers. Pending requests fail with RuntimeError."""
        if self._closed:
            return
        self._closed = True
        if self.mode == "thread":
            for _ in self._threads:
                self._task_q.put(None)
            for t in self._threads:
                t.join(timeout=60)
        elif self.mode == "process":
            for _ in self._procs:
                with contextlib.suppress(Exception):
                    self._task_q.put(None)
            for p in self._procs:
                p.join(timeout=60)
            self._terminate()
        elif self.mode == "single":
            self._model.release()
        self._fail_all(RuntimeError("NLIPool closed"))

    def _terminate(self) -> None:
        for p in self._procs:
            if p.is_alive():
                p.terminate()

    def __enter__(self) -> "NLIPool":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"NLIPool({self.name!r}, mode={self.mode!r}, devices={self.devices!r})"


# --------------------------------------------------------------------------------------------------
# Reading JSONL (plain, .gz, .zst, .zip, .rar, .parquet; files, folders, globs)
# --------------------------------------------------------------------------------------------------

try:
    import nli_formats
except ImportError:  # pragma: no cover - nli_formats.py lives next to this file
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import nli_formats

SUPPORTED_SUFFIXES = nli_formats.INPUT_SUFFIXES  # .jsonl .json .ndjson (+ .gz .zst .zstd) .zip .rar .parquet


def zstd_available() -> bool:
    if zstandard is not None:
        return True
    try:
        from compression import zstd  # noqa: F401  (Python 3.14+)
        return True
    except ImportError:
        return False


def _is_supported(name: str) -> bool:
    return name.lower().endswith(SUPPORTED_SUFFIXES)


def _zstd_reader(raw: BinaryIO) -> BinaryIO:
    if zstandard is not None:
        reader = zstandard.ZstdDecompressor(max_window_size=2 ** 31).stream_reader(raw, read_across_frames=True)
        return io.BufferedReader(reader, buffer_size=1 << 20)
    try:
        from compression import zstd
    except ImportError:
        raise RuntimeError("reading .zst files needs the 'zstandard' package (pip install zstandard)") from None
    return zstd.ZstdFile(raw, "rb")


def _decoded(name: str, raw: BinaryIO) -> BinaryIO:
    low = name.lower()
    if low.endswith((".zst", ".zstd")):
        return _zstd_reader(raw)
    if low.endswith(".gz"):
        return gzip.GzipFile(fileobj=raw, mode="rb")
    return raw


class _Counting(io.RawIOBase):
    """Passes reads through and adds their size to owner.bytes_read."""

    def __init__(self, fh: BinaryIO, owner: Any):
        self._fh, self._owner = fh, owner

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        data = self._fh.read(len(b))
        n = len(data)
        b[:n] = data
        self._owner.bytes_read += n
        return n


@dataclass
class Record:
    """One input line. data is the parsed object (None for blank or broken lines, see error)."""
    source: str                 # file path, or "archive.zip!member.jsonl"
    line: int                   # 1-based line number in the decompressed file / member
    data: Optional[Any]
    raw: bytes                  # the original line without the line ending
    error: Optional[str] = None  # None, "blank" or "bad_json: ..."

    def get(self, field: str, default: Any = None) -> Any:
        return self.data.get(field, default) if isinstance(self.data, dict) else default


class JsonlSource:
    """
    One input file: .jsonl/.json/.ndjson, the same compressed with .gz or .zst, a .zip or .rar of them, or a
    .parquet table (row n = line n, see nli_formats.py).
    path may be a local path or a RemoteFile (nli_storage.expand_remote: a file on FTP / SFTP / S3), which is
    streamed from the server (a .zip / .rar / .parquet is downloaded to a temporary file first). local = an
    already downloaded copy to read instead; Record.source still names path.
    """

    def __init__(self, path: PathLike, local: Optional[PathLike] = None):
        self.path = str(path)
        self.remote = path if hasattr(path, "storage") and local is None else None
        self.local = str(local) if local is not None else None
        self.bytes_read = 0  # bytes of the (compressed) file read so far: progress of a run

    @contextlib.contextmanager
    def _open_raw(self) -> Iterator[BinaryIO]:
        if self.remote is not None:
            with self.remote.open() as fh:
                yield io.BufferedReader(_Counting(fh, self), buffer_size=1 << 18)
        else:
            with open(self.local or self.path, "rb") as fh:
                yield io.BufferedReader(_Counting(fh, self), buffer_size=1 << 18)

    @contextlib.contextmanager
    def _local_file(self) -> Iterator[str]:
        """A real file for the formats that need one (.zip / .rar / .parquet): downloaded first if remote."""
        if self.remote is None:
            yield self.local or self.path
            with contextlib.suppress(OSError):
                self.bytes_read = os.path.getsize(self.local or self.path)  # read as a whole: done at the end
            return
        import tempfile
        from nli_storage import download
        fd, tmp = tempfile.mkstemp(suffix=Path(self.path).suffix, prefix="nli_")
        os.close(fd)
        try:
            download(self.remote, tmp)
            yield tmp
        finally:
            with contextlib.suppress(OSError):
                os.remove(tmp)

    @contextlib.contextmanager
    def _open_members(self) -> Iterator[Iterator[Tuple[str, BinaryIO]]]:
        low = self.path.lower()

        def usable(name: str) -> bool:  # members: (compressed) JSONL, not archives / tables inside archives
            return _is_supported(name) and not nli_formats.needs_local_file(name)

        if low.endswith(".zip"):
            with self._local_file() as zpath, zipfile.ZipFile(zpath) as zf:
                def members():
                    for info in zf.infolist():
                        if info.is_dir() or not usable(info.filename):
                            continue
                        with zf.open(info) as raw, contextlib.closing(_decoded(info.filename, raw)) as fh:
                            yield f"{self.path}!{info.filename}", fh
                yield members()
        elif low.endswith(".rar"):
            with self._local_file() as rpath:
                def members():
                    for name in nli_formats.rar_members(rpath):
                        if not usable(name):
                            continue
                        with nli_formats.open_rar_member(rpath, name) as raw, \
                                contextlib.closing(_decoded(name, raw)) as fh:
                            yield f"{self.path}!{name}", fh
                yield members()
        elif nli_formats.is_table(low):  # .parquet / .arrow / .feather
            with self._local_file() as ppath:
                lines = (nli_formats.parquet_lines(ppath) if low.endswith(".parquet")
                         else nli_formats.arrow_lines(ppath))
                stream = io.BufferedReader(nli_formats.IterStream(lines),
                                           buffer_size=1 << 20)
                with contextlib.closing(stream) as fh:
                    yield iter([(self.path, fh)])
        else:
            with self._open_raw() as raw, contextlib.closing(_decoded(self.path, raw)) as fh:
                yield iter([(self.path, fh)])

    def records(self, parse: bool = True, limit: Optional[int] = None) -> Iterator[Record]:
        """Yield every line as a Record (blank and broken lines included, with error set)."""
        count = 0
        with self._open_members() as members:
            for source, fh in members:
                for n, line in enumerate(fh, 1):
                    if limit is not None and count >= limit:
                        return
                    count += 1
                    raw = line.rstrip(b"\r\n")
                    if not raw.strip():
                        yield Record(source, n, None, raw, "blank")
                        continue
                    if not parse:
                        yield Record(source, n, None, raw)
                        continue
                    try:
                        yield Record(source, n, json_loads(raw), raw)
                    except ValueError as exc:
                        yield Record(source, n, None, raw, f"bad_json: {exc}")

    def __repr__(self) -> str:
        return f"JsonlSource({self.path!r})"


def _is_url(item: str) -> bool:
    return bool(re.match(r"^(ftps?|sftp|s3|minios?)://", item, re.IGNORECASE))


def expand_inputs(inputs: Union[PathLike, Sequence[PathLike]], recursive: bool = True) -> List[str]:
    """
    Files, folders (searched recursively for supported files) and glob patterns -> sorted unique file list.
    Server URLs (ftp:// ftps:// sftp:// s3:// minio://, see nli_storage.py) give RemoteFile items: a folder,
    one file, or a pattern such as sftp://user:pw@host/data/corpus/**/*.zst.
    """
    if isinstance(inputs, (str, os.PathLike)):
        inputs = [inputs]
    files: List[str] = []
    for item in inputs:
        if not isinstance(item, str) or not hasattr(item, "storage"):
            item = str(item)
        if hasattr(item, "storage"):  # already a RemoteFile
            files.append(item)
        elif _is_url(item):
            try:
                from nli_storage import expand_remote
            except ImportError:
                raise RuntimeError("server input needs nli_storage.py next to nli_models.py") from None
            files.extend(expand_remote(item, _is_supported))
        elif os.path.isdir(item):
            for root, dirs, names in os.walk(item):
                dirs.sort()
                files.extend(os.path.join(root, n) for n in sorted(names) if _is_supported(n))
                if not recursive:
                    break
        elif any(ch in item for ch in "*?["):
            matches = sorted(glob.glob(item, recursive=True))
            if not matches:
                raise FileNotFoundError(f"no files match {item}")
            files.extend(m for m in matches if os.path.isfile(m))
        elif os.path.isfile(item):
            files.append(item)
        else:
            raise FileNotFoundError(item)
    seen, out = set(), []
    for f in files:
        key = str(f) if hasattr(f, "storage") else os.path.normcase(os.path.abspath(f))
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def iter_sources(inputs: Union[PathLike, Sequence[PathLike]], recursive: bool = True) -> Iterator[JsonlSource]:
    for path in expand_inputs(inputs, recursive):
        yield JsonlSource(path)


def iter_records(inputs: Union[PathLike, Sequence[PathLike]], parse: bool = True,
                 limit: Optional[int] = None) -> Iterator[Record]:
    """All lines of all inputs, in order."""
    count = 0
    for src in iter_sources(inputs):
        for rec in src.records(parse=parse):
            if limit is not None and count >= limit:
                return
            count += 1
            yield rec


# --------------------------------------------------------------------------------------------------
# Writing (plain, .gz, .zst), atomically
# --------------------------------------------------------------------------------------------------


def open_output(path: PathLike, binary: bool = False, level: int = 3, compression: Optional[str] = None):
    """Open a file for writing; compression from the suffix (.zst / .gz) unless given ("zst", "gz", "none")."""
    path = str(path)
    kind = compression or ("zst" if path.lower().endswith((".zst", ".zstd")) else
                           "gz" if path.lower().endswith(".gz") else "none")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if kind == "zst":
        raw = open(path, "wb")
        if zstandard is not None:
            stream = zstandard.ZstdCompressor(level=level, threads=-1).stream_writer(raw, closefd=True)
        else:
            try:
                from compression import zstd
            except ImportError:
                raw.close()
                raise RuntimeError("writing .zst files needs the 'zstandard' package (pip install zstandard)") from None
            stream = zstd.ZstdFile(raw, "wb", level=level)
        return stream if binary else io.TextIOWrapper(stream, encoding="utf-8", newline="\n")
    if kind == "gz":
        return gzip.open(path, "wb" if binary else "wt", compresslevel=6, **({} if binary else {"encoding": "utf-8"}))
    return open(path, "wb") if binary else open(path, "w", encoding="utf-8", newline="\n")


class AtomicOutput:
    """
    Write to "<path>.tmp<suffix>" and rename to path on success; the temporary file is removed on error,
    so a finished output file is always complete.

        with AtomicOutput("out/x.jsonl.zst") as fh:
            fh.write("...\\n")
    """

    def __init__(self, path: PathLike, binary: bool = False, level: int = 3):
        self.path = Path(path)
        name = self.path.name
        suffix = "".join(s for s in self.path.suffixes if s.lower() in (".zst", ".zstd", ".gz"))
        self.tmp = self.path.with_name(f"{name}.tmp{suffix}")
        self.binary, self.level = binary, level
        self.fh = None

    def __enter__(self):
        self.fh = open_output(self.tmp, self.binary, self.level)
        return self.fh

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.fh.close()
        finally:
            if exc_type is None:
                os.replace(self.tmp, self.path)
            else:
                with contextlib.suppress(OSError):
                    os.remove(self.tmp)


# --------------------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nli_models.py", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Zero-shot NLI scoring with the local models: texts or JSONL files x hypotheses -> P(entailment).",
        epilog=__doc__.split("Command line\n------------\n", 1)[1].split("\nEvery probability", 1)[0])
    g = p.add_argument_group("model")
    g.add_argument("--model", default="modernbert", help="modernbert | deberta | bge-m3 | folder | HF ID (default modernbert)")
    g.add_argument("--models-root", help="folder holding the model folders (default ./models or $NLI_MODELS_ROOT)")
    g.add_argument("--list-models", action="store_true", help="show the known models and whether they are found")
    g.add_argument("--check", metavar="MODELS", help="load models (comma list or 'all'), score sample pairs, exit")
    g = p.add_argument_group("what to score")
    g.add_argument("--text", action="append", default=[], help="a text to score (repeatable)")
    g.add_argument("--input", action="append", default=[],
                   help="JSONL file / folder / glob; .gz .zst .zip .rar .parquet .arrow ok (repeatable)")
    g.add_argument("--text-field", default="text", help="JSON field with the text (default text)")
    g.add_argument("--id-field", default="id", help="JSON field copied to the output (default id)")
    g.add_argument("--limit", type=int, help="stop after this many input lines")
    g.add_argument("--hypothesis", action="append", default=[], help="hypothesis sentence (repeatable)")
    g.add_argument("--labels", help="comma-separated labels, turned into hypotheses with --template")
    g.add_argument("--template", default="This text is about {}.", help="label -> hypothesis (default 'This text is about {}.')")
    g.add_argument("--single-label", action="store_true", help="normalise label scores to sum 1 per text")
    g.add_argument("--threshold", type=float, help="also list the hypotheses scoring >= this value")
    g = p.add_argument_group("hardware and parallelism")
    g.add_argument("--device", default="auto", help="auto | cpu | cuda | cuda:0,cuda:1 | 0,1 | cpu*4 (default auto)")
    g.add_argument("--mode", default="auto", choices=NLIPool.MODES, help="single | thread | process (default auto)")
    g.add_argument("--workers-per-device", type=int, default=1, help="workers on each device (default 1)")
    g.add_argument("--dtype", default="auto", help="auto | bf16 | fp16 | fp32 (default auto)")
    g.add_argument("--batch-size", type=int, default=32, help="pairs per batch (default 32)")
    g.add_argument("--max-batch-tokens", type=int, help="also cap a batch at about this many tokens")
    g.add_argument("--max-length", type=int, help="tokens per pair, longer premises are cut (default 512)")
    g.add_argument("--cpu-threads", type=int, help="torch threads per CPU worker")
    g.add_argument("--compile", action="store_true", help="torch.compile the model (Linux + triton)")
    g.add_argument("--chunk-size", type=int, default=256, help="input lines per request (default 256)")
    g.add_argument("--inflight", type=int, default=4, help="requests queued at once (default 4)")
    g = p.add_argument_group("output")
    g.add_argument("--out", help="output JSONL (.zst / .gz to compress); default stdout")
    g.add_argument("--digits", type=int, default=4, help="decimals in the scores (default 4)")
    g.add_argument("-v", "--verbose", action="store_true")
    return p


SANITY_PAIRS = [
    ("Moscow is the capital of Russia and its largest city.", "This text is about Russia.", True),
    ("Preheat the oven to 200 degrees and roast the vegetables for 25 minutes.", "This text is about Russia.", False),
    ("Russian River Brewing Company released a new IPA.", "This text mentions Russian only as part of a company or brand name.", True),
]


def _cmd_list(args) -> int:
    reg = ModelRegistry(args.models_root)
    print(f"models root: {reg.models_root}")
    for spec, folder, ok in reg.available():
        print(f"  {spec.key:<11} {'found  ' if ok else 'MISSING'} {spec.folder:<34} {spec.languages:<15} "
              f"max {spec.max_length:<5} {spec.role}")
        print(f"  {'':<11} aliases: {', '.join(spec.aliases)}")
    print(f"zstandard: {'yes' if zstd_available() else 'no (pip install zstandard to read/write .zst)'}   "
          f"orjson: {'yes' if orjson else 'no'}")
    return 0


def _cmd_check(args) -> int:
    names = list(MODEL_SPECS) if args.check.strip().lower() == "all" else [n.strip() for n in args.check.split(",")]
    failed = 0
    for name in names:
        try:
            model = NLIModel(name, device=resolve_devices(args.device)[0], dtype=args.dtype,
                             models_root=args.models_root, max_length=args.max_length)
        except Exception as exc:
            print(f"[FAIL] {name}: {exc}")
            failed += 1
            continue
        t0 = time.perf_counter()
        scores = model.score_pairs([p for p, _, _ in SANITY_PAIRS], [h for _, h, _ in SANITY_PAIRS])
        dt = time.perf_counter() - t0
        # the first two pairs are easy and must be right; the third (role of a word) is hard, shown for information
        ok = all((s >= 0.5) == want for s, (_, _, want) in zip(scores[:2], SANITY_PAIRS[:2]))
        failed += not ok
        print(f"[{'OK' if ok else 'FAIL'}] {model!r} loaded {model.load_seconds:.1f}s, 3 pairs {dt:.2f}s | "
              f"about Russia {scores[0]:.3f} (want high), unrelated {scores[1]:.3f} (want low), "
              f"company-name role {scores[2]:.3f} (hard case, ideally high)")
        model.release()
        del model
    return 1 if failed else 0


def _cmd_score(args) -> int:
    hyps = list(args.hypothesis)
    if args.labels:
        hyps += [args.template.format(l.strip()) if "{}" in args.template else f"{args.template} {l.strip()}"
                 for l in args.labels.split(",") if l.strip()]
    if not hyps:
        print("error: give --hypothesis and/or --labels", file=sys.stderr)
        return 2
    if not args.text and not args.input:
        print("error: give --text or --input", file=sys.stderr)
        return 2

    def items() -> Iterator[Dict[str, Any]]:
        for i, t in enumerate(args.text, 1):
            yield {"source": "--text", "line": i, "id": None, "text": t}
        if args.input:
            for rec in iter_records(args.input, limit=args.limit):
                text = rec.get(args.text_field)
                yield {"source": rec.source, "line": rec.line, "id": rec.get(args.id_field) if args.id_field else None,
                       "text": text if isinstance(text, str) else None, "error": rec.error}

    pool = NLIPool(args.model, devices=args.device, mode=args.mode, workers_per_device=args.workers_per_device,
                   batch_size=args.batch_size, max_batch_tokens=args.max_batch_tokens, dtype=args.dtype,
                   max_length=args.max_length, models_root=args.models_root, cpu_threads=args.cpu_threads,
                   compile=args.compile)
    info = pool.info()
    print(f"model {info['model']} | mode {info['mode']} | devices {','.join(info['devices'])} | dtype {info['dtype']} "
          f"| max_length {info['max_length']} | loaded in {info['load_seconds']:.1f}s", file=sys.stderr)
    out = AtomicOutput(args.out) if args.out else contextlib.nullcontext(sys.stdout)
    pending: collections.deque = collections.deque()
    n_lines = n_scored = 0
    t0 = time.perf_counter()

    def flush_one(fh) -> None:
        nonlocal n_scored
        chunk, fut = pending.popleft()
        scores = fut.result()
        k = 0
        for item in chunk:
            row: Dict[str, Any] = {"source": item["source"], "line": item["line"]}
            if item["id"] is not None:
                row["id"] = item["id"]
            if item["text"] is None:
                row["error"] = item.get("error") or "no_text"
            else:
                s = scores[k * len(hyps):(k + 1) * len(hyps)]
                k += 1
                n_scored += 1
                row["scores"] = {h: round(v, args.digits) for h, v in zip(hyps, s)}
                if args.single_label:
                    total = sum(s) or 1.0
                    row["scores"] = {h: round(v / total, args.digits) for h, v in zip(hyps, s)}
                if args.threshold is not None:
                    row["above"] = [h for h, v in row["scores"].items() if v >= args.threshold]
            fh.write(json_dumps(row) + "\n")

    try:
        with out as fh:
            for chunk in _chunks(items(), args.chunk_size):
                texts = [it["text"] for it in chunk if it["text"] is not None]
                pending.append((chunk, pool.submit([t for t in texts for _ in hyps], hyps * len(texts))))
                n_lines += len(chunk)
                while len(pending) > max(1, args.inflight):
                    flush_one(fh)
            while pending:
                flush_one(fh)
    finally:
        pool.close()
    dt = time.perf_counter() - t0
    pairs = n_scored * len(hyps)
    print(f"{n_lines} lines, {n_scored} texts scored, {pairs} pairs in {dt:.1f}s "
          f"({pairs / dt if dt else 0:.1f} pairs/s){' -> ' + args.out if args.out else ''}", file=sys.stderr)
    return 0


def _chunks(it, size: int):
    buf = []
    for x in it:
        buf.append(x)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8")
    if not args.verbose:
        quiet_transformers()
    if args.list_models:
        return _cmd_list(args)
    if args.check:
        return _cmd_check(args)
    try:
        return _cmd_score(args)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
