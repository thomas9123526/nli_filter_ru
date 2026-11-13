"""Print which packages from whl_files_need.txt are not installed in this Python environment."""
import importlib.metadata as md
import platform
import sys

NAMES = """transformers tokenizers safetensors huggingface_hub hf_xet regex typer click rich shellingham
annotated_doc markdown_it_py mdurl pygments httpx2 httpcore2 anyio h11 idna truststore packaging pyyaml
tqdm orjson pyahocorasick zstandard sentencepiece protobuf pyarrow
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

# optional: corpus input from a server (sftp:// needs paramiko, s3:// / minio:// need boto3; ftp:// nothing)
OPTIONAL = {"sftp://": "paramiko bcrypt cryptography invoke pynacl cffi pycparser".split(),
            "s3:// minio://": "boto3 botocore jmespath s3transfer python-dateutil six urllib3".split()}
print("\nOptional, only for a corpus on a server (see the end of whl_files_need.txt):")
for what, names in OPTIONAL.items():
    gone = []
    for name in names:
        try:
            md.version(name)
        except md.PackageNotFoundError:
            gone.append(name)
    print(f"  {what:<15}", "all installed" if not gone else "missing: " + " ".join(gone))

# the result viewer (normally its own venv, viewer/backend/.venv; run this script with that python to check it)
VIEWER = {"viewer": "fastapi uvicorn starlette pydantic zstandard orjson boto3 paramiko".split(),
          "viewer tests": "pytest httpx pyftpdlib moto flask werkzeug cfn-lint".split()}
print("\nResult viewer (run with viewer\\backend\\.venv\\Scripts\\python.exe to check the viewer's venv):")
for what, names in VIEWER.items():
    gone = []
    for name in names:
        try:
            md.version(name)
        except md.PackageNotFoundError:
            gone.append(name)
    print(f"  {what:<15}", "all installed" if not gone else "missing: " + " ".join(gone))
print("  install offline: see the VIEWER section at the end of whl_files_need.txt")
