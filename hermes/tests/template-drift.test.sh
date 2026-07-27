#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/ristretto-drift-test.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

export RISTRETTO_HERMES_HOME="$tmp/hermes"
mkdir -p "$tmp/hermes"
seeds="$tmp/hermes/.template-seeds"

pass=0
fail=0

assert() {
  local description="$1"
  shift
  if "$@"; then
    pass=$((pass + 1))
    printf 'ok %d - %s\n' "$pass" "$description"
  else
    fail=$((fail + 1))
    printf 'not ok - %s\n' "$description" >&2
  fi
}

out="$(bash "$repo/scripts/template-drift.sh")"
assert "first run baselines a missing seed record" test -f "$seeds"
assert "first run says it baselined" grep -q "baselined" <<<"$out"

out="$(bash "$repo/scripts/template-drift.sh")"
assert "clean record reports templates ok" grep -q "templates ok" <<<"$out"

sed -i.bak 's/^SOUL.md .*/SOUL.md 0000000000000000/' "$seeds" && rm -f "$seeds.bak"
out="$(bash "$repo/scripts/template-drift.sh")"
assert "stale seed reports drift" grep -q "SOUL.md changed upstream" <<<"$out"
assert "drift output names the ack command" grep -q -- "--ack" <<<"$out"
assert "drift never touches the user copy" grep -q "untouched" <<<"$out"
assert "drift run still exits zero" \
  bash -c "bash '$repo/scripts/template-drift.sh' >/dev/null"

bash "$repo/scripts/template-drift.sh" --ack >/dev/null
out="$(bash "$repo/scripts/template-drift.sh")"
assert "ack clears the drift" grep -q "templates ok" <<<"$out"

assert "unknown flag is rejected" \
  bash -c "! bash '$repo/scripts/template-drift.sh' --bogus 2>/dev/null"

printf 'template-drift.test.sh: %d passed, %d failed\n' "$pass" "$fail"
exit "$((fail > 0 ? 1 : 0))"
