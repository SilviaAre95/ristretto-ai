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
runtime="${RISTRETTO_STATE_HOME:-$HOME/.ristretto}/runtime"
base="${1:-main}"

origin="$(git -C "$repo" remote get-url origin 2>/dev/null || true)"
if [ -z "$origin" ]; then
  echo "install-runtime: no origin remote in $repo" >&2
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
if [ ! -x "$venv/bin/python" ]; then
  echo "creating $venv"
  python3 -m venv "$venv"
fi
"$venv/bin/python" -m pip install --quiet --upgrade pip
# Installed from the runtime directory, so the package it imports is the one
# beside it rather than the development tree.
"$venv/bin/python" -m pip install --quiet -e "$runtime"

# Prove it: a runtime that cannot import what it is meant to run is not a
# runtime, and finding that out at launch costs an hour.
"$venv/bin/python" -c "import ristretto.runner" || {
  echo "install-runtime: the runtime venv cannot import ristretto.runner" >&2
  exit 1
}

echo "runtime pinned at origin/$base ($commit)"
echo "flows now run from $runtime, not from $repo"
