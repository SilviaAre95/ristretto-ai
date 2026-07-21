#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv="$repo/.venv"

command -v git >/dev/null || {
  echo "setup-dev: git is required" >&2
  exit 1
}

python_bin="${PYTHON_BIN:-}"
if [ -z "$python_bin" ]; then
  if command -v python3.11 >/dev/null; then
    python_bin="$(command -v python3.11)"
  elif command -v python3 >/dev/null; then
    python_bin="$(command -v python3)"
  else
    echo "setup-dev: Python 3.11 is required" >&2
    exit 1
  fi
fi

python_version="$($python_bin -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [ "$python_version" != "3.11" ]; then
  echo "setup-dev: Python 3.11 is required; $python_bin is $python_version" >&2
  echo "Set PYTHON_BIN to a Python 3.11 executable and retry." >&2
  exit 1
fi

if [ ! -d "$venv" ]; then
  "$python_bin" -m venv "$venv"
  # A fresh venv lacks the build tooling that --no-build-isolation relies on.
  "$venv/bin/python" -m pip install --upgrade pip setuptools wheel
elif [ "$("$venv/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" != "3.11" ]; then
  echo "setup-dev: existing .venv does not use Python 3.11" >&2
  echo "Move or remove .venv, then retry." >&2
  exit 1
fi

if [ "${RISTRETTO_UPGRADE_PIP:-0}" = "1" ]; then
  "$venv/bin/python" -m pip install --upgrade pip
fi

# Reuse the venv's build tooling instead of creating an isolated build env.
# This keeps repeat setup runs working without network access once dependencies
# have been installed at least once.
"$venv/bin/python" -m pip install --no-build-isolation -r "$repo/requirements-dev.txt"
bash "$repo/scripts/install-private-push-guard.sh"

echo "Development environment ready."
echo "Activate it with: source .venv/bin/activate"
echo "Then run: make check"
