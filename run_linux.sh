#!/usr/bin/env bash
# HoN Net Guard — Linux launcher (needs root for tc shaping)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")")"

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Run with: sudo ./run_linux.sh"
    exec sudo -E env \
      DISPLAY="${DISPLAY:-}" \
      XAUTHORITY="${XAUTHORITY:-${HOME}/.Xauthority}" \
      HOME="${HOME}" \
      PYTHONPATH="$(pwd)" \
      bash "$(pwd)/run_linux.sh" "$@"
  fi
}

need_root "$@"

# Prefer the invoking user's home for config when under sudo
if [[ -n "${SUDO_USER:-}" ]]; then
  USER_HOME="$(getent passwd "$SUDO_USER" | cut -d: -f6 || true)"
  if [[ -n "${USER_HOME:-}" ]]; then
    export HOME="$USER_HOME"
  fi
  if [[ -z "${DISPLAY:-}" ]]; then
    export DISPLAY=":0"
  fi
  if [[ -z "${XAUTHORITY:-}" && -f "$HOME/.Xauthority" ]]; then
    export XAUTHORITY="$HOME/.Xauthority"
  fi
fi

PYTHON=python3
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "python3 not found"
  exit 1
fi

# Install deps only if missing (avoid hanging pip every launch)
if ! "$PYTHON" -c "import psutil" 2>/dev/null; then
  "$PYTHON" -m pip install --user -q -r requirements.txt 2>/dev/null || \
    "$PYTHON" -m pip install -q -r requirements.txt
fi

if ! "$PYTHON" -c "import tkinter" 2>/dev/null; then
  echo "tkinter missing. Fedora: sudo dnf install python3-tkinter"
  echo "Ubuntu/Debian: sudo apt install python3-tk"
  exit 1
fi

if ! command -v tc >/dev/null 2>&1; then
  echo "tc missing. Install iproute2"
  exit 1
fi

export PYTHONPATH="$(pwd)${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" -u main.py
