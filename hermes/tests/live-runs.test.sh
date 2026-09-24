#!/usr/bin/env bash
# Tests for live-runs.sh: both run shapes are detected, and a quiet machine
# reports nothing. The classic shape is the regression under test — the guard
# in install-runtime.sh matched only the staged runner, so a live run-loop.sh
# passed straight through it.
#
# Plain string of pids rather than an array: /bin/bash on macOS is 3.2 and has
# no negative array subscripts.
set -uo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/ristretto-live-runs-test.XXXXXX")"
started=""
cleanup() {
  for pid in $started; do kill "$pid" 2>/dev/null || true; done
  rm -rf "$tmp"
}
trap cleanup EXIT

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

stop() {
  kill "$1" 2>/dev/null || true
  wait "$1" 2>/dev/null || true
  sleep 0.4
}

# A quiet machine. Guard against a real run on the developer's box producing a
# false pass here — the other two cases are the ones that matter.
if ! bash "$repo/scripts/live-runs.sh" >/dev/null; then
  assert "nothing live exits 1" true
else
  printf '# skipped the quiet-machine case: a run is live on this box\n'
fi

# Classic: a foreground run-loop.sh, matched by its pinned path.
mkdir -p "$tmp/loop-runner/scripts"
printf '#!/usr/bin/env bash\nsleep 30\n' > "$tmp/loop-runner/scripts/run-loop.sh"
chmod +x "$tmp/loop-runner/scripts/run-loop.sh"
bash "$tmp/loop-runner/scripts/run-loop.sh" &
classic=$!
started="$started $classic"
sleep 0.4
out="$(bash "$repo/scripts/live-runs.sh")"
assert "a live classic loop is reported" grep -q "run-loop.sh" <<<"$out"
assert "a live classic loop exits 0" \
  bash -c "bash '$repo/scripts/live-runs.sh' >/dev/null"
stop "$classic"

# Staged: the runner's own command line.
bash -c "exec -a 'python3 -m ristretto.runner --task-id t_abc123 --flow full' sleep 30" &
staged=$!
started="$started $staged"
sleep 0.4
out="$(bash "$repo/scripts/live-runs.sh")"
assert "a live staged runner is reported" grep -q "ristretto.runner --task-id" <<<"$out"
stop "$staged"

# A shell that merely names the runner is not running it. This is the case
# `pgrep -f` got wrong: it matches the command line of whatever runs the
# search, so a monitor watching for a flow reported itself as one. Verified
# against the old implementation, which reported this process as a live run.
#
# The loop is load-bearing: `bash -c` with a single simple command execs it
# and the shell's own argv — comment included — disappears, so the fixture
# would pass against any implementation.
bash -c 'while :; do sleep 1; done # -m ristretto.runner --task-id t_notreal' &
mentioner=$!
started="$started $mentioner"
sleep 0.4
if out="$(bash "$repo/scripts/live-runs.sh")"; then
  assert "a shell that only mentions the runner is not reported" \
    bash -c "! grep -q t_notreal <<<'$out'"
else
  assert "a shell that only mentions the runner is not reported" true
fi
stop "$mentioner"

# The guards must run BEFORE the destructive step, not merely exist. Checked
# statically rather than by executing update.sh, because a guard that failed
# would then pull and reinstall against the developer's own checkout.
before() {
  local guard step file
  file="$1"; guard="$(grep -n 'live-runs.sh' "$file" | head -1 | cut -d: -f1)"
  step="$(grep -n "$2" "$file" | head -1 | cut -d: -f1)"
  [ -n "$guard" ] && [ -n "$step" ] && [ "$guard" -lt "$step" ]
}
assert "update.sh checks for live runs before pulling" \
  before "$repo/scripts/update.sh" 'git pull'
assert "install-runtime.sh checks for live runs before touching the runtime" \
  before "$repo/scripts/install-runtime.sh" 'git -C "\$runtime"'

printf '\nlive-runs.test.sh: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
