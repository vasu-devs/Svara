#!/bin/sh
# Svara on Linux: ./run.sh [--bench|--test 5|--list-devices|-v ...]
cd "$(dirname "$0")" || exit 1
[ -x .venv/bin/python ] || { uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -r requirements-linux.txt; } || exit 1
[ "$1" = "--onboard" ] && exec sh -c 'echo onboard > "$XDG_RUNTIME_DIR/svara-hotkey.fifo"'   # toggle the voice session in the running Svara
exec .venv/bin/python -m mywhisper --config config-linux.yaml --no-tray "$@"
