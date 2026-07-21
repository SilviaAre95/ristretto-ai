#!/usr/bin/env bash
# Export the committed public tree into a fresh, staged Git repository without
# private history. The destination must not exist; this script never overwrites
# or deletes a destination.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
destination="${1:-}"

if [ -z "$destination" ]; then
  echo "usage: scripts/export-public.sh <new-destination>" >&2
  exit 2
fi
case "$destination" in
  /*) ;;
  *)
    echo "export-public: destination must be an absolute path" >&2
    exit 2
    ;;
esac
if [ -e "$destination" ]; then
  echo "export-public: destination already exists: $destination" >&2
  exit 1
fi

cd "$repo"
if [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
  echo "export-public: commit tracked changes before exporting" >&2
  exit 1
fi
bash scripts/check-public.sh

mkdir -p "$destination"
git archive --format=tar HEAD | tar -xf - -C "$destination"
git -C "$destination" init -q -b main
git -C "$destination" add .
(cd "$destination" && bash scripts/check-public.sh)

echo "Fresh public repository exported and staged without private history: $destination"
echo "Review it, configure a privacy-safe git identity, then create the first commit."
