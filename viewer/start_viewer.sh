#!/usr/bin/env bash
# Start the NLI result viewer on Linux / macOS: http://127.0.0.1:8000
#   ./start_viewer.sh                         # uses viewer_config.json next to this script
#   CONFIG=my.json PORT=8080 HOST=0.0.0.0 ./start_viewer.sh
#   WHEELS=../pkgs/h200-ubuntu-py312 ./start_viewer.sh   # first run without internet: install from a wheel folder
# First run: creates backend/.venv, installs the Python packages, builds the frontend if npm is available.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
CONFIG=${CONFIG:-$HERE/viewer_config.json}
PORT=${PORT:-8000}
HOST=${HOST:-127.0.0.1}
PY=$HERE/backend/.venv/bin/python

if [ ! -x "$PY" ]; then
    echo "Creating Python environment in $HERE/backend/.venv ..."
    "${PYTHON:-python3}" -m venv "$HERE/backend/.venv"
    SOURCE=()
    if [ -n "${WHEELS:-}" ]; then
        echo "Installing offline from $WHEELS ..."
        SOURCE=(--no-index --find-links "$WHEELS")
    fi
    if ! "$PY" -m pip install -q "${SOURCE[@]}" -r "$HERE/backend/requirements.txt"; then
        # a half-installed environment would be taken as ready on the next start: remove it
        rm -rf "$HERE/backend/.venv"
        echo "Installing the Python packages failed (see above); backend/.venv was removed, fix the cause and start again." >&2
        exit 1
    fi
fi
if [ "${REBUILD:-0}" = "1" ] || [ ! -f "$HERE/frontend/out/index.html" ]; then
    if command -v npm >/dev/null; then
        echo "Building the frontend ..."
        (cd "$HERE/frontend" && { [ -d node_modules ] || npm install --no-audit --no-fund; } && NEXT_TELEMETRY_DISABLED=1 npm run build)
    else
        echo "warning: npm not found: the API runs, but the web pages need frontend/out (build elsewhere and copy it)" >&2
    fi
fi
cd "$HERE/backend"
exec "$PY" -m nli_viewer serve --config "$CONFIG" --host "$HOST" --port "$PORT"
