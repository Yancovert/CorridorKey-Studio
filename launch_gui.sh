#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -x "$SCRIPT_DIR/venv/bin/python" ]; then
    exec "$SCRIPT_DIR/venv/bin/python" -m gui.app "$@"
elif [ -x "$SCRIPT_DIR/venv/bin/python3" ]; then
    exec "$SCRIPT_DIR/venv/bin/python3" -m gui.app "$@"
elif [ -d "$SCRIPT_DIR/venv" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
    exec python3 -m gui.app "$@"
else
    exec python3 -m gui.app "$@"
fi
