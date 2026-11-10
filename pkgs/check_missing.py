"""Print which packages from whl_files_need.txt are not installed in this Python environment."""
import importlib.metadata as md
import platform
import sys

NAMES = """transformers tokenizers safetensors huggingface_hub hf_xet regex typer click rich shellingham
annotated_doc markdown_it_py mdurl pygments httpx2 httpcore2 anyio h11 idna truststore packaging pyyaml
tqdm orjson pyahocorasick zstandard sentencepiece protobuf
torch numpy filelock fsspec jinja2 markupsafe sympy mpmath networkx typing_extensions""".split()
if sys.version_info < (3, 11):
    NAMES += ["exceptiongroup", "tomli"]
if platform.system() == "Windows":
    NAMES += ["colorama"]

print(f"Python {platform.python_version()} on {platform.system()}")
missing = []
for name in NAMES:
    try:
        print(f"  ok       {name} {md.version(name)}")
    except md.PackageNotFoundError:
        missing.append(name)
        print(f"  MISSING  {name}")
print("\nCopy the wheels for:", " ".join(missing) if missing else "(nothing missing)")
