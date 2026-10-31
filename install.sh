#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v python3 &>/dev/null; then
    echo "error: python3 is not installed or not on PATH."
    exit 1
fi

# launch gui installer if x11 or wayland display is available, else fallback to cli
if [ -n "$DISPLAY" ] || [ -n "$WAYLAND_DISPLAY" ]; then
    exec python3 install_gui.py "$@"
else
    exec python3 install.py "$@"
fi
