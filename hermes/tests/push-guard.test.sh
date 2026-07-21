#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

git -C "$TMP" init -q -b main
git -C "$TMP" config user.name "Ristretto Test"
git -C "$TMP" config user.email "test@example.invalid"
touch "$TMP/root"
git -C "$TMP" add root
git -C "$TMP" commit -qm root
PRIVATE_ROOT="$(git -C "$TMP" rev-parse HEAD)"

if printf 'refs/heads/main %s refs/heads/main %040d\n' "$PRIVATE_ROOT" 0 | \
  (cd "$TMP" && RISTRETTO_PRIVATE_ROOT_COMMIT="$PRIVATE_ROOT" "$ROOT/.githooks/pre-push" origin unused) \
  >/dev/null 2>&1; then
  echo "not ok - private-history descendant was allowed" >&2
  exit 1
fi
echo "ok - private-history descendant is blocked"

git -C "$TMP" switch -q --orphan public
touch "$TMP/public"
git -C "$TMP" add public
git -C "$TMP" commit -qm public
PUBLIC_ROOT="$(git -C "$TMP" rev-parse HEAD)"
printf 'refs/heads/public %s refs/heads/public %040d\n' "$PUBLIC_ROOT" 0 | \
  (cd "$TMP" && RISTRETTO_PRIVATE_ROOT_COMMIT="$PRIVATE_ROOT" "$ROOT/.githooks/pre-push" origin unused)
echo "ok - unrelated fresh history is allowed"

printf 'refs/heads/main %040d refs/heads/main %s\n' 0 "$PRIVATE_ROOT" | \
  (cd "$TMP" && RISTRETTO_PRIVATE_ROOT_COMMIT="$PRIVATE_ROOT" "$ROOT/.githooks/pre-push" origin unused)
echo "ok - remote branch deletion is allowed"
