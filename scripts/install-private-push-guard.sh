#!/usr/bin/env bash
# Protect this private working repository from accidentally publishing its
# inherited history. A history-free public export does not contain the sentinel
# commit, so this installer intentionally leaves exported repositories alone.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
private_root="${RISTRETTO_PRIVATE_ROOT_COMMIT:-4ebdb7a3919a48cba84bf39ccd424fcdd9221210}"

if ! git -C "$repo" cat-file -e "${private_root}^{commit}" 2>/dev/null; then
  echo "push-guard: private-history sentinel absent; no hook installed"
  exit 0
fi

git -C "$repo" config core.hooksPath .githooks
echo "push-guard: installed for this private repository"
