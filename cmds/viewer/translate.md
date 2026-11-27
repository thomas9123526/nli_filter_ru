# Translating texts in the viewer

The viewer can translate the texts it shows into the languages listed in `targets` (one button each, with its
English name, e.g. **Russian**). Translation is **for reading only**:
labels and decisions always come from the original text.

The backend is `viewer/backend/nli_viewer/translate.py`. Its tests are in `viewer/backend/tests/test_translate.py`.

## Settings (`viewer/viewer_config.json`)

    "translate": {
      "targets": ["zh", "ru"],
      "providers": [
        {"name": "qwen", "kind": "openai", "base_url": "http://192.168.170.108:8000/v1", "model": "qwen3-4b",
         "api_key_env": "QWEN_API_KEY", "timeout": 60, "no_think": true},
        {"name": "hunyuan", "kind": "openai", "base_url": "http://127.0.0.1:8001/v1", "model": "Hunyuan-MT-7B",
         "prompt": "hunyuan", "timeout": 120},
        {"name": "hunyuan_local", "kind": "local", "base_url": "http://127.0.0.1:8002/v1", "model": "Hunyuan-MT-7B",
         "prompt": "hunyuan", "timeout": 180, "enabled": false}
      ]
    }

The provider keys:

| key | meaning |
|---|---|
| `name` | shown on the page ("translated by qwen"); must be unique |
| `kind` | `openai`: any OpenAI-compatible server (vLLM, the Qwen service). `local`: the same protocol, served by `tools/serve_translate_local.py`. Defaults to `127.0.0.1:8001`, `prompt: hunyuan`, timeout 180 s. |
| `base_url` | ends in `/v1` |
| `model` | the served model name, as shown by `GET /v1/models`. When the 35B Qwen model is served, change only this. |
| `api_key_env` | the name of an environment variable that holds the key. If it is unset or empty, no `Authorization` header is sent. **A key written in the config itself (`"api_key"`) is refused.** |
| `timeout` | seconds per call |
| `no_think` | Qwen3: sends `chat_template_kwargs: {"enable_thinking": false}` |
| `no_think_tag` | also add `/no_think` to the message. Off by default: on qwen3-4b it made half the answers start with "Assistant:". |
| `prompt` | `generic` (system + user message) or `hunyuan` (the Hunyuan-MT model card template) |
| `enabled` | `false` skips the provider; it can still be tested or forced |
| `temperature`, `max_tokens`, `max_chars` | optional. Defaults: 0.2 (generic) / 0.7 (hunyuan); about 3 tokens per character; paragraphs over 3000 characters are split further. |

Top-level options: `concurrency` (4 texts at once) and `down_seconds` (30). An unreachable provider is skipped for
`down_seconds`, so every text does not wait for its timeout.

The block is read from the viewer's config file. **It is read again when the file changes**, so there is no need to
restart the viewer. The translate buttons follow `targets` (after a page reload).

### Changing the providers on the page (`/label/translate/`)

Without editing the file: each provider has ↑ ↓ (the order auto tries them in), **used by auto** (on / off), and its
**URL**, **model** and **timeout (s)**. "Save to viewer_config.json" writes them into the `translate` block:

- only that block is rewritten (one line per provider); the rest of the file, its comments included, stays byte for
  byte. Comments inside the block are not kept. The old file goes to `viewer\.backup\viewer_config.json.<time>`;
- every other provider key (`kind`, `prompt`, `api_key_env`, `no_think` …) stays as it was; switching one back on
  removes its `"enabled": false`;
- checked first like a load (URL must start with `http://` / `https://`, timeout 1–3600 s, no empty model); refused
  when the file changed since the page loaded it ("reload the page");
- used at once, no restart.

**Test** checks the URL / model / timeout typed in the row, saved or not, so a new server can be tried before saving.

### Choosing the provider for one translation

The translation panel next to a text has **using: auto (in order) / qwen / hunyuan / …**. Auto is the order above, with
the fallback. Choosing one uses only that provider (no fallback; also one switched off for auto). The choice is
remembered in this browser for every page.

## How it works

**Providers are tried in order.** A provider has failed when:
- there is no connection, or the call times out;
- it returns an HTTP error, an answer that is not a chat completion, or an empty answer;
- its answer is **in the wrong language twice**: the first answer is in the wrong language, and so is the retry with a
  stricter prompt.

The answer shows which provider translated it (`provider`), and `fallback: true` when that was not the first one. It
also lists the errors of the providers that failed.

**The prompts:**
- **Generic (Qwen).** The system message says: "You are a professional translator. Translate the user's text into
  Chinese (简体中文) … Output only the translation." The user message names the language again: "Translate the following
  text into Chinese (简体中文). Output only the translation." followed by the text (Russian: "Russian (русский язык)").
  The stricter retry adds one worked example (Borscht → 罗宋汤… / Борщ…) before the text.
- **Hunyuan-MT**, from the model card. Chinese: `把下面的文本翻译成中文，不要额外解释。\n\n<text>`. Other targets:
  `Translate the following segment into Russian, without additional explanation.\n\n<text>`. There is no system
  message: the model has none. Sampling as in the model card and `generation_config.json`: `top_k 20, top_p 0.6,
  repetition_penalty 1.05, temperature 0.7`.

**Cleaning the answer.** `<think>…</think>` blocks are removed. So are a lone `</think>` (everything before it), an
unclosed `<think>` (everything after it) and a leading "Assistant:" / "Translation:" label.

**Language check, by script.** Digits and punctuation are ignored. One CJK character counts as 1 unit; one word in an
alphabetic script also counts as 1 unit. The answer passes when:
- the target script (CJK for zh, Cyrillic for ru) makes up at least **50 %** of all units, so a few Latin names are
  fine;
- and at least **80 %** of the non-Latin units, so Cyrillic in a Chinese answer, or Japanese kana, fail it.

An answer under 3 units passes unless another script dominates. Untranslated English fails.

The check catches a wrong language, **not** a bad translation.

**Long texts.** With `texts`, each text is split on blank lines; a paragraph over `max_chars` is split further, on line
ends and then on sentence ends. Each piece is translated on its own, and the pieces are joined back with exactly the
same breaks. So paragraph *n* of the translation is paragraph *n* of the original. With `paragraphs`, each item is
translated as one piece. All pieces of a text use the same provider: if one piece fails, the next provider translates
the text.

**Cache.** The cache is in `<cache_dir>/translate/` (`viewer/.viewer_cache/translate/`, which git ignores). There is
one JSON file per piece, keyed by sha256 of (text, target, provider, model, prompt, prompt version). A cached piece is
used even when its provider is down. `"nocache": true` translates again and overwrites the entry.

**Keys** are read from the environment on every call. They are never put in the config, logs, error messages or
responses; error messages are scrubbed of the key as well. The settings API shows only `api_key_env` and `has_key`.

## API (for the frontend)

`POST /api/translate`:

    {"texts": ["Shchi, a cabbage soup ...\n\nSecond paragraph."], "target": "zh"}
    // or {"paragraphs": ["p1", "p2"], "target": "ru"}; optional "provider": "hunyuan" (only this one, no fallback),
    // "nocache": true

The answer always has **HTTP 200** when the request is valid, even when every provider failed. Then `ok` is false and
there is an error per text, so a batch can partly succeed:

    {"target": "zh", "ok": true, "failed": 0, "error": null,
     "results": [{"index": 0, "ok": true, "translation": "…\n\n…", "provider": "qwen", "model": "qwen3-4b",
                  "fallback": false, "cached": false, "pieces": 2, "seconds": 1.3,
                  "notes": ["answer not in Chinese (main script cyrillic), retried with a stricter prompt"],
                  "errors": []}]}

    // both failed:
    {"target": "zh", "ok": false, "failed": 1, "error": "1 of 1 not translated: no provider could translate: qwen: HTTP 500: …; hunyuan: cannot connect to http://127.0.0.1:8001/v1: …",
     "results": [{"index": 0, "ok": false, "translation": null, "provider": null, "fallback": false, …,
                  "errors": [{"provider": "qwen", "model": "qwen3-4b", "error": "HTTP 500: …"},
                             {"provider": "hunyuan", "model": "Hunyuan-MT-7B", "error": "cannot connect …"}],
                  "error": "no provider could translate: qwen: …; hunyuan: …"}]}

Other status codes:
- **400**: an unknown target, a target missing from `targets`, both or neither of `texts` / `paragraphs`, or an
  unknown `provider`;
- **413**: more than 500 items or 400,000 characters;
- **503**: no `translate` block.

`GET /api/translate/settings`:

    {"configured": true, "source": "D:\\…\\viewer_config.json",
     "targets": [{"code": "zh", "name": "Chinese", "label": "简体中文"}, {"code": "ru", "name": "Russian", "label": "русский язык"}],
     "providers": [{"name": "qwen", "kind": "openai", "base_url": "…", "model": "qwen3-4b", "timeout": 60.0,
                    "no_think": true, "no_think_tag": false, "prompt": "generic", "enabled": true,
                    "api_key_env": "QWEN_API_KEY", "has_key": false}, …],
     "cache_dir": "…\\.viewer_cache\\translate", "concurrency": 4, "down_seconds": 30.0,
     "editable": true, "mtime": "1795700000123456789"}

`POST /api/translate/settings/save` (the page's Save): `{"mtime": "<from the settings>", "providers": [{"name": "hunyuan",
"enabled": true, "base_url": "http://127.0.0.1:8001/v1", "model": "Hunyuan-MT-7B", "timeout": 120}, {"name": "qwen", …}]}`:
every provider exactly once, in the new order. Answer: `{"saved": "<file>", "backup": "<file>", "mtime": "…",
"providers": […]}`. **400**: a bad value or a provider missing / twice / unknown; **409**: the file changed since
`mtime`, or the settings do not come from a file.

`POST /api/translate/test`, with the body `{}` or `{"provider": "qwen", "targets": ["zh"], "text": "…"}`; with one
provider, `"override": {"base_url": …, "model": …, "timeout": …}` tests those values instead (not saved). The default
text is a benchmark sentence. The test does not use the cache or the fallback:

    {"text": "Shchi, …",
     "providers": [{"name": "qwen", "model": "qwen3-4b", "base_url": "…", "enabled": true,
                    "reachable": true, "models": ["qwen3-4b"], "model_served": true, "error": null, "seconds": 0.05,
                    "samples": [{"target": "zh", "ok": false, "translation": "Щи, …", "seconds": 0.7,
                                 "language": {"ok": false, "target_share": 0.0, "main_script": "cyrillic", …},
                                 "error": "answer not in Chinese; the stricter retry prompt fixed it",
                                 "retry": {"ok": true, "translation": "…", "language": {…}}},
                                {"target": "ru", "ok": true, …}]},
                   {"name": "hunyuan", "reachable": false, "models": [], "error": "ConnectError: …", "samples": []}]}

## The test endpoint on this PC (qwen3-4b), 2026-11-25

Endpoint: `http://192.168.170.108:8000/v1`. It is vLLM serving `qwen3-4b`, with no key, 0.6–1.8 s per sentence.
The test used benchmark sentences from `dataset/corpus_benchmark` (Russian food v1, Ukrainian food v1).

- **Wrong language.** The Shchi sentence asked for Chinese came back in **Russian** in 4 of 8 tries with the plain
  prompt. That was so with the system + user prompt, with the target named in both messages, with a Chinese system
  prompt and with the instruction after the text; a Chinese-only user prompt was worse (7 of 8). A one-shot example
  fixed it (0 of 8), so the stricter retry uses one. Asked for Russian, one answer stayed in English; the retry fixed
  it.
- **The language check caught every wrong-language answer.** In the pipeline, all 8 test translations (4 texts × zh /
  ru) ended in the right language, two of them after the retry.
- **The `/no_think` tag** in the message made 4 of 8 answers start with "Assistant:". It is off by default; any
  leftover label is removed anyway. `enable_thinking: false` alone is enough.
- **Quality is weak for names of dishes**, which the language check cannot see:
  - Shchi → 肉汁 ("gravy");
  - Beef Stroganoff → 草原牛肉沙拉 ("steppe beef salad"), with a stray 草原 at the end;
  - Holubtsi → "Выпечка" ("pastry");
  - Deruny → "пельмени";
  - Chernihiv → "ченегов".

  Plain sentences are fine. **Do not read fine details from qwen3-4b translations.** Compare again on ~20 benchmark
  texts once the 35B model is served.

## Hunyuan-MT-7B, the fallback

### Licence (checked 2026-11-25: `License.txt` in the Hugging Face repo, the "Tencent Hunyuan Community License")

- **Territory:** worldwide, except a few excluded regions (the EU, the UK and others: see `License.txt` for the list). Use,
  and use of its output, outside the Territory is not licensed. **Do not run it, or use its translations, in an
  excluded region.** This is about the place, not the language: translating into German or French outside those
  regions is fine.
- **Commercial use:** allowed, royalty-free. A licensee whose products had more than 100 million monthly active users
  must ask Tencent.
- **Outputs:** Tencent claims no rights in them. However, **"You must not use the Tencent Hunyuan Works or any Output … to
  improve any other AI model"** (other than Hunyuan). The labelled data in this project is for an LLM, so **its
  translations must never go into training data, label files or test sets.** They are for reading in the viewer only,
  which is how the viewer uses them. Labels come from the original text.
- **Other terms:** follow the Acceptable Use Policy (Exhibit A) and pass its use restrictions on if you redistribute
  the model; keep the notice; no Tencent trademarks.
- **Result:** fine for internal research reading, outside the excluded regions. **If that does not fit**, use
  Seed-X-PPO-7B (OpenMDW licence) with the same setup (`"prompt": "generic"`, or a template of its own).

### Download

The model is about 16 GB: bf16, 4 safetensors shards. Download it to `models/Hunyuan-MT-7B`, which git ignores
(`models/**`):

    pip install huggingface_hub     # the viewer's .venv does not have it
    python -c "from huggingface_hub import snapshot_download; snapshot_download('tencent/Hunyuan-MT-7B', local_dir='models/Hunyuan-MT-7B')"

**Status on 2026-11-25: not downloaded.** D: had only ~35 GB free, and the plan says skip under 60 GB.

**For the offline H200:** copy the whole `models/Hunyuan-MT-7B` folder, including `tokenizer_config.json` (which holds
the chat template) and `generation_config.json`. The pip packages are vllm (Linux), or transformers>=4.56 + accelerate
+ torch. Add them to the pkgs / offline notes.

### On a PC without a GPU: a 4-bit GGUF with llama.cpp

The full model (15 GB in bf16) does not fit next to Windows in 16 GB of RAM. A 4-bit quantized copy does: the community
conversion `Mungert/Hunyuan-MT-7B-GGUF` (not from Tencent; same licence), file `Hunyuan-MT-7B-q4_k_m.gguf`, 4.4 GB.
`llama-server` speaks the same OpenAI-compatible API, so the `hunyuan` provider (port 8001, model `Hunyuan-MT-7B`) uses
it without a config change.

    winget install ggml.llamacpp
    python -c "from huggingface_hub import hf_hub_download; hf_hub_download('Mungert/Hunyuan-MT-7B-GGUF', 'Hunyuan-MT-7B-q4_k_m.gguf', local_dir='models/Hunyuan-MT-7B-GGUF')"
    llama-server -m models\Hunyuan-MT-7B-GGUF\Hunyuan-MT-7B-q4_k_m.gguf --alias Hunyuan-MT-7B --port 8001 --jinja -c 4096

About 5–6 GB of RAM while running. Slower than a GPU (several seconds per sentence) and slightly lower quality than
bf16. Smaller files (`q3_k_m` 3.5 GB) use less RAM and are worse; `q5_k_m` (5.1 GB) is a little better.

### Serving with vLLM (Linux / WSL / the H200)

    vllm serve /path/to/models/Hunyuan-MT-7B --served-model-name Hunyuan-MT-7B --port 8001 \
        --dtype bfloat16 --max-model-len 8192 --gpu-memory-utilization 0.5
    curl http://127.0.0.1:8001/v1/models

vLLM applies the chat template from `tokenizer_config.json`. It accepts `top_k` and `repetition_penalty` in the
request body, which the viewer sends. Fully offline: add `HF_HUB_OFFLINE=1` and pass the local folder path.

### Serving on this Windows PC without WSL: `tools/serve_translate_local.py`

This is a minimal OpenAI-compatible server (`/v1/models`, `/v1/chat/completions`, `/health`). It uses transformers
in bf16 on CUDA, applies the model's chat template (Hunyuan-MT: without a generation prompt, as the model card does),
and answers one request at a time.

    python tools/serve_translate_local.py --model models/Hunyuan-MT-7B --port 8001
    # served name = folder name (Hunyuan-MT-7B); --host 0.0.0.0 to open it to the LAN

**On port 8001**, the `hunyuan` provider uses it, so nothing changes in the config. The `hunyuan_local` entry
(`"kind": "local"`, port 8002, disabled) is for running it next to a vLLM on 8001: start it with `--port 8002` and set
`"enabled": true`.

**It needs torch with CUDA.** An RTX 5090 (sm_120) needs a CUDA 12.8+ build, plus transformers>=4.56 and accelerate:

    pip install torch --index-url https://download.pytorch.org/whl/cu128
    pip install "transformers>=4.56" accelerate

On 2026-11-25 there was no such environment here: `py -3` has `torch 2.14.1+cpu`, and the viewer venv has no torch. So
the server was checked only with a stub model, through the viewer's fallback path (connection refused on the first
provider → the local server answered zh and ru).

**Still to check, once the model is downloaded and CUDA torch is installed:** start the server, then press the
settings panel's test button, or call `POST /api/translate/test` with `{"provider": "hunyuan"}`.
