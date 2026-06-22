#!/usr/bin/env bash
# Minerva Can FixDAT — launcher that activates the virtual environment.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "Error: Virtual environment not found at $SCRIPT_DIR/.venv/"
    echo "Create it with:  python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

exec "$VENV_PYTHON" "$SCRIPT_DIR/minerva_gui.py" "$@"
