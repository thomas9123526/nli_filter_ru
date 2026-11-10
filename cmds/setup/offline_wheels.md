# Offline wheels: which ones each machine needs

Notes from the setup session of 2026-11-09 / 10: git identity, the wheel lists in `pkgs/`, a smaller
wheel set for machines that already have torch + CUDA, and whether transformers 4.x can be used.

Run every command from the project folder `D:\hkc\nli_filter2`.

## 1. Git name and email (this repo only)

```
git config --local user.name "Isabel"
git config --local user.email "isabelrrr1@outlook.com"
```

Other repos on the machine are not affected. Use `--global` instead of `--local` to set it everywhere.

## 2. What the scripts need

`nli_filter.py`, `nli_models.py` and `make_test_corpus.py` import only the standard library plus:

| Package | Why | Required? |
|---|---|---|
| torch 2.11.0+cu128 | runs the models | yes |
| transformers 5.20.2 | loads the models (4.57.6 also works, see section 6) | yes |
| zstandard | reads and writes `.zst` files; `make_test_corpus.py` | yes for `.zst` (Python 3.10 / 3.12 have no built-in zstd) |
| orjson | faster JSON | optional, falls back to `json` |
| pyahocorasick | faster keyword search | optional, falls back to regex |
| sentencepiece, protobuf | tokenizer fallback for DeBERTa-v3 / bge-m3 | safety net, `tokenizer.json` is used first |

## 3. The two lists in `pkgs/`

| File | What it lists |
|---|---|
| `pkgs/whl_files.txt` | Every wheel for a machine with nothing installed: torch + CUDA libraries included (2.8 GB Windows, 4 GB Linux). The paths point to `D:\hkc\nli_country_filter\pkgs\{windows,linux}`. |
| `pkgs/whl_files_need.txt` | Only what a machine that **already has torch + CUDA** is missing (about 25-33 MB). Leaves out torch, triton, `nvidia_*` / `cuda_*`, numpy, and torch's own dependencies (filelock, fsspec, jinja2, markupsafe, mpmath, networkx, sympy, typing_extensions, setuptools). |

Both lists have four sections: `rtx5090-windows-py310`, `windows-py312`, `rtx5090-ubuntu-py310`,
`h200-ubuntu-py312`. Windows Python 3.12 = the Python 3.10 list with cp312 wheels, minus `exceptiongroup`
and `tomli` (only Python < 3.11 needs them). The full set for Windows Python 3.12 (with torch) is not downloaded.

## 4. The smaller wheel set, one folder per machine

The wheels in `whl_files_need.txt` are in `pkgs/<machine>/`. Copy only the folder for your machine.

| Folder | Wheels | Size |
|---|---|---|
| `pkgs/rtx5090-windows-py310/` | 31 | 25.5 MB |
| `pkgs/windows-py312/` | 29 | 25.4 MB |
| `pkgs/rtx5090-ubuntu-py310/` | 30 | 32.4 MB |
| `pkgs/h200-ubuntu-py312/` | 28 | 32.4 MB |

Wheels already in `nli_country_filter\pkgs` were copied. The rest were downloaded from PyPI on 2026-11-10:
zstandard 0.25.0 for every machine (about 0.5 MB on Windows, about 5.3 MB on Linux), and orjson, pyahocorasick,
pyyaml, regex and sentencepiece for Windows Python 3.12.

Each set was checked with an offline `pip install --dry-run` against the full torch wheels. For the two RTX 5090
machines, everything outside the torch stack resolved from the machine's folder: nothing missing, nothing extra.
For the H200, the test also asked for exceptiongroup and tomli. Those are only needed on Python 3.10, and the
request came from running the test under Python 3.10 on the Windows computer, so the H200 folder is complete
without them. The Windows Python 3.12 folder could not be tested this way because there is no cp312 torch
wheel to resolve against.

How a missing wheel was downloaded (example, Linux Python 3.12):

```
pip download zstandard==0.25.0 --no-deps --only-binary=:all: --python-version 3.12 --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux_2_28_x86_64 -d pkgs/h200-ubuntu-py312
```

## 5. Installing on a machine that already has torch + CUDA

Copy `pkgs/check_missing.py` and the machine's folder, then:

```
python pkgs/check_missing.py
pip install --no-index --find-links pkgs/<machine-folder> transformers==5.20.2 orjson pyahocorasick zstandard sentencepiece protobuf
```

`check_missing.py` prints each package as `ok` or `MISSING`, including torch and numpy. pip keeps the torch that is
already installed. If pip says `No matching distribution found for X`, X was not installed after all: copy X's
wheel from the full set (`whl_files.txt`) as well.

## 6. Can transformers 4.x be used?

Yes, **4.48 or newer** (newest 4.x: **4.57.6**). Version 4.48 is the first with ModernBERT. The other two models
(DeBERTa-v3, bge-m3 = XLM-RoBERTa) work with older 4.x too. `nli_models.py` already handles both versions: it
passes `dtype=` on 4.56+ and `torch_dtype=` before that. Every other transformers call it makes (`AutoTokenizer`,
`AutoConfig`, `AutoModelForSequenceClassification`, `reference_compile` for ModernBERT, the logging helpers)
exists in 4.48+. This was checked by reading the code. The scripts have not been run with 4.x yet.

transformers 4.57.6 needs different versions of some packages than the 5.x set:

| Package | 4.57.6 set | 5.20.2 set |
|---|---|---|
| transformers | 4.57.6 | 5.20.2 |
| huggingface_hub | 0.36.2 | 2.4.0 |
| tokenizers | 0.22.2 | 0.23.3 |
| requests, urllib3, certifi, charset_normalizer | needed (new) | not needed |
| typer, click, rich, shellingham, annotated_doc, markdown_it_py, mdurl, pygments, httpx2, httpcore2, anyio, h11, truststore, hf_xet, exceptiongroup, tomli | not needed | needed |

Everything else (safetensors, regex, pyyaml, packaging, tqdm, idna, colorama, orjson, pyahocorasick, zstandard,
sentencepiece, protobuf) is the same. So the 4.x set is smaller. The 4.x wheels are **not downloaded yet**.
To get them for one machine (example: Windows Python 3.10):

```
pip download transformers==4.57.6 huggingface_hub==0.36.2 tokenizers==0.22.2 requests urllib3 certifi charset_normalizer --only-binary=:all: --no-deps --python-version 3.10 --platform win_amd64 -d pkgs/rtx5090-windows-py310-tf4
pip install --no-index --find-links pkgs/rtx5090-windows-py310-tf4 --find-links pkgs/rtx5090-windows-py310 transformers==4.57.6 orjson pyahocorasick zstandard sentencepiece protobuf
```

Do not install transformers 4.x and 5.x in the same environment. Pick one.
