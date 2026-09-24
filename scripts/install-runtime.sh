#!/usr/bin/env bash
# Build or update the checkout that dispatched flows run from.
#
# A flow runs for an hour unattended. Until this existed it ran from the
# development checkout — an editable install and symlinked skills — so it
# executed whatever was in that tree at the moment it started, including
# uncommitted edits and whichever branch was out. This gives it a copy nobody
# is editing.
#
# Cloned from the *remote*, not from the local checkout, so what runs is
# provably what is on the server rather than what someone fetched once.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# eval so a configured ~ expands the way events.state_home() expands it with
# .expanduser(); without it the script builds ./~/... while every launch looks
# under $HOME and reports itself unpinned forever.
eval runtime="${RISTRETTO_STATE_HOME:-$HOME/.ristretto}/runtime"
base="${1:-main}"

origin="$(git -C "$repo" remote get-url origin 2>/dev/null || true)"
if [ -z "$origin" ]; then
  echo "install-runtime: no origin remote in $repo" >&2
  exit 1
fi

# Refuse while a flow is live, and do it BEFORE anything is moved. The install
# is editable and the update is a checkout, so files change under a running
# flow — and its later stages re-read them: the broker is respawned per stage
# and several imports are lazy. That is the exact failure this feature exists
# to remove, relocated one directory over.
live="$(pgrep -f "ristretto\.runner --task-id" 2>/dev/null | tr '\n' ' ' || true)"
if [ -n "$live" ]; then
  echo "install-runtime: refusing while a flow is running (pids: $live)" >&2
  echo "  updating would swap code under it — stop it, or wait" >&2
  exit 1
fi

if [ -d "$runtime/.git" ]; then
  echo "updating $runtime"
  git -C "$runtime" remote set-url origin "$origin"
  git -C "$runtime" fetch --quiet origin "$base"
else
  echo "cloning $origin into $runtime"
  mkdir -p "$(dirname "$runtime")"
  git clone --quiet "$origin" "$runtime"
  git -C "$runtime" fetch --quiet origin "$base"
fi

# Refuse to move a runtime someone has edited. Overwriting it would discard
# their change silently, and a pinned checkout that is secretly modified is
# worse than an honest development one.
if [ -n "$(git -C "$runtime" status --porcelain)" ]; then
  echo "install-runtime: $runtime has local changes; refusing to overwrite" >&2
  git -C "$runtime" status --short >&2
  exit 1
fi

# Detached on purpose: there is no branch to accidentally commit to, and the
# recorded commit is exactly what was chosen.
git -C "$runtime" checkout --quiet --detach "origin/$base"
commit="$(git -C "$runtime" rev-parse --short=12 HEAD)"

venv="$runtime/.venv"
# The project refuses anything but 3.11 for development (setup-dev.sh) and CI
# pins it; an hour-long unattended run should not silently land on whatever
# `python3` happens to be, which with Homebrew is routinely newer.
py="${PYTHON_BIN:-python3}"
version="$("$py" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo unknown)"
if [ "$version" != "3.11" ]; then
  echo "install-runtime: need Python 3.11, found $version ($py)" >&2
  echo "  set PYTHON_BIN to a 3.11 interpreter" >&2
  exit 1
fi
if [ ! -x "$venv/bin/python" ]; then
  echo "creating $venv"
  "$py" -m venv "$venv"
fi
"$venv/bin/python" -m pip install --quiet --upgrade pip
# Installed from the runtime directory, so the package it imports is the one
# beside it rather than the development tree.
"$venv/bin/python" -m pip install --quiet -e "$runtime"

# Prove it — from a neutral directory and with -P. Run from the repository
# root, which is where make puts us, `python -m`/`-c` place the cwd first on
# sys.path and the check imports the *development* tree: a runtime whose
# install never landed would pass and print "pinned". Verified 2026-09-20.
( cd / && env -u PYTHONPATH -u PYTHONHOME -u VIRTUAL_ENV \
    "$venv/bin/python" -P -c "
import ristretto.runner, pathlib, sys
here = pathlib.Path(ristretto.runner.__file__).resolve()
want = pathlib.Path('$runtime').resolve()
sys.exit(0 if want in here.parents else 1)
" ) || {
  echo "install-runtime: the runtime venv does not import ristretto from $runtime" >&2
  rm -rf "$venv"
  echo "  removed the incomplete venv so launches stay honestly unpinned" >&2
  exit 1
}

# Re-point the loop-runner skill now that a runtime exists. Without this the
# classic path keeps running from the working checkout, and the pin would
# cover the staged flows only — which is the half-pinned state this script's
# own docstring describes as the problem.
bash "$repo/scripts/link-loop-runner.sh" || {
  echo "install-runtime: runtime is pinned but the loop-runner link was not updated" >&2
  echo "  classic runs will keep using $repo until that is resolved" >&2
  exit 1
}

echo "runtime pinned at origin/$base ($commit)"
echo "flows now run from $runtime, not from $repo"
