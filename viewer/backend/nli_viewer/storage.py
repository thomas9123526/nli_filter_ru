"""
Storage for the viewer: local disk, FTP(S), SFTP, S3 / MinIO.

The code lives in nli_storage.py in the project root (nli_filter.py uses it too, to read corpora from
servers); this module re-exports it under the old name nli_viewer.storage. When the viewer is copied
somewhere else, copy nli_storage.py next to it or onto PYTHONPATH.
"""
import sys
from pathlib import Path

try:
    import nli_storage as _impl
except ImportError:
    _root = Path(__file__).resolve().parents[3]  # viewer/backend/nli_viewer/storage.py -> project root
    if (_root / "nli_storage.py").is_file():
        sys.path.insert(0, str(_root))
    import nli_storage as _impl

from nli_storage import *  # noqa: E402,F401,F403
from nli_storage import __all__  # noqa: E402,F401
