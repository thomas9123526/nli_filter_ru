"""
serve_translate_local.py - a minimal OpenAI-compatible server for a local translation model (Hunyuan-MT-7B), for
Windows without WSL / vLLM. transformers + torch (CUDA, bf16). One request at a time.

    python tools/serve_translate_local.py --model models/Hunyuan-MT-7B --port 8001
    # then in viewer_config.json the "hunyuan" provider (base_url http://127.0.0.1:8001/v1) uses it

Endpoints:
    GET  /v1/models              {"data": [{"id": "<served name>"}]}
    POST /v1/chat/completions    {"model", "messages", "max_tokens", "temperature", "top_p", "top_k",
                                  "repetition_penalty"} -> {"choices": [{"message": {"role": "assistant", ...}}]}
    GET  /health

Needs: torch with CUDA (an RTX 5090 needs a CUDA 12.8+ build: pip install torch --index-url
https://download.pytorch.org/whl/cu128), transformers>=4.56, accelerate. Bound to 127.0.0.1 unless --host is given.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List


class Engine:
    def __init__(self, model_dir: str, device: str = "cuda", dtype: str = "bfloat16"):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model_dir)
        self.model = AutoModelForCausalLM.from_pretrained(model_dir, torch_dtype=getattr(torch, dtype),
                                                          device_map=device)
        self.model.eval()
        tpl = self.tok.chat_template or ""
        # Hunyuan-MT's template has no generation prompt (the user turn already ends with the assistant marker);
        # the model card calls apply_chat_template(..., add_generation_prompt=False)
        self.add_generation_prompt = "add_generation_prompt" in tpl
        gen = getattr(self.model, "generation_config", None)
        self.defaults = {k: getattr(gen, k) for k in ("temperature", "top_p", "top_k", "repetition_penalty")
                         if gen is not None and getattr(gen, k, None) is not None}
        self.lock = threading.Lock()

    def chat(self, messages: List[Dict[str, str]], params: Dict[str, Any]) -> Dict[str, Any]:
        torch = self.torch
        ids = self.tok.apply_chat_template(messages, tokenize=True, add_generation_prompt=self.add_generation_prompt,
                                           return_tensors="pt").to(self.model.device)
        p = {**self.defaults, **{k: params[k] for k in ("temperature", "top_p", "top_k", "repetition_penalty")
                                 if params.get(k) is not None}}
        temperature = float(p.get("temperature", 0.7))
        kw = dict(max_new_tokens=int(params.get("max_tokens") or 2048), do_sample=temperature > 0,
                  repetition_penalty=float(p.get("repetition_penalty", 1.0)))
        if temperature > 0:
            kw.update(temperature=temperature, top_p=float(p.get("top_p", 1.0)), top_k=int(p.get("top_k", 0)))
        with self.lock, torch.inference_mode():
            out = self.model.generate(ids, attention_mask=torch.ones_like(ids), **kw)
        new = out[0][ids.shape[1]:]
        text = self.tok.decode(new, skip_special_tokens=True).strip()
        return {"text": text, "prompt_tokens": int(ids.shape[1]), "completion_tokens": int(new.shape[0])}


def make_server(engine: Any, served_name: str, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):   # no request bodies in the log
            print(f"{self.address_string()} {fmt % args}")

        def _send(self, code: int, obj: Dict[str, Any]) -> None:
            raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path.rstrip("/") in ("/v1/models", "/models"):
                self._send(200, {"object": "list", "data": [{"id": served_name, "object": "model",
                                                             "owned_by": "local"}]})
            elif self.path.rstrip("/") in ("/health", ""):
                self._send(200, {"status": "ok", "model": served_name})
            else:
                self._send(404, {"error": {"message": f"no route {self.path}"}})

        def do_POST(self):
            if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
                return self._send(404, {"error": {"message": f"no route {self.path}"}})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                messages = body["messages"]
                if body.get("stream"):
                    return self._send(400, {"error": {"message": "stream is not supported"}})
            except (ValueError, KeyError) as exc:
                return self._send(400, {"error": {"message": f"bad request: {exc}"}})
            if body.get("model") and body["model"] != served_name:
                return self._send(404, {"error": {"message": f"model {body['model']} is not served "
                                                             f"(this server: {served_name})"}})
            t0 = time.time()
            try:
                r = engine.chat(messages, body)
            except Exception as exc:   # report, keep serving
                return self._send(500, {"error": {"message": f"{type(exc).__name__}: {exc}"}})
            print(f"  generated {r['completion_tokens']} tokens in {time.time() - t0:.1f}s")
            self._send(200, {"id": f"chatcmpl-{uuid.uuid4().hex}", "object": "chat.completion",
                             "created": int(time.time()), "model": served_name,
                             "choices": [{"index": 0, "finish_reason": "stop",
                                          "message": {"role": "assistant", "content": r["text"]}}],
                             "usage": {"prompt_tokens": r["prompt_tokens"],
                                       "completion_tokens": r["completion_tokens"],
                                       "total_tokens": r["prompt_tokens"] + r["completion_tokens"]}})

    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    root = Path(__file__).resolve().parents[1]
    ap.add_argument("--model", default=str(root / "models" / "Hunyuan-MT-7B"), help="model folder")
    ap.add_argument("--name", default=None, help="served model name (default: the folder name)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--dtype", default="bfloat16")
    a = ap.parse_args()
    name = a.name or Path(a.model).name
    print(f"loading {a.model} ({a.dtype}, {a.device}) ...")
    t0 = time.time()
    engine = Engine(a.model, a.device, a.dtype)
    print(f"loaded in {time.time() - t0:.0f}s; serving '{name}' on http://{a.host}:{a.port}/v1 (Ctrl+C stops)")
    srv = make_server(engine, name, a.host, a.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
