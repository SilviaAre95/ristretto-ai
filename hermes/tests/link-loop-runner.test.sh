#!/usr/bin/env bash
# The classic loop must follow the pinned runtime, not the checkout you edit.
set -u
PASS=0; FAIL=0
t() { if eval "$2"; then echo "ok  - $1"; PASS=$((PASS+1)); else echo "FAIL - $1"; FAIL=$((FAIL+1)); fi; }

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$ROOT/scripts/link-loop-runner.sh"
TMP="$(mktemp -d)"
HH="$TMP/hermes"
STATE="$TMP/state"
DEST="$HH/skills/software-development/loop-runner"
mkdir -p "$HH/skills/software-development"

run() { CUZAM_HERMES_HOME="$HH" CUZAM_STATE_HOME="$STATE" bash "$SCRIPT" "$@"; }

# No runtime yet: a fresh install must still work, and must say it is unpinned.
OUT="$(run 2>&1)"; RC=$?
t "no runtime: succeeds"            "[ $RC -eq 0 ]"
t "no runtime: links the checkout"  "[ \"\$(readlink '$DEST')\" = '$ROOT/hermes/skills/loop-runner' ]"
t "no runtime: says it is unpinned" "printf '%s' \"\$OUT\" | grep -q 'no runtime pinned'"

# Runtime appears: the link must move without needing the old one removed.
mkdir -p "$STATE/runtime/hermes/skills/loop-runner/scripts"
: > "$STATE/runtime/hermes/skills/loop-runner/scripts/run-loop.sh"
OUT="$(run 2>&1)"; RC=$?
t "runtime present: succeeds"       "[ $RC -eq 0 ]"
t "runtime present: relinks"        "[ \"\$(readlink '$DEST')\" = '$STATE/runtime/hermes/skills/loop-runner' ]"
t "runtime present: says pinned"    "printf '%s' \"\$OUT\" | grep -q 'pinned runtime'"

# Idempotent.
run >/dev/null 2>&1
t "second run is a no-op"           "[ \"\$(readlink '$DEST')\" = '$STATE/runtime/hermes/skills/loop-runner' ]"

# A half-cloned runtime has the directory but not the script. Linking to it
# would break every classic run, so the checkout must win.
rm "$DEST"
rm "$STATE/runtime/hermes/skills/loop-runner/scripts/run-loop.sh"
run >/dev/null 2>&1
t "incomplete runtime: falls back"  "[ \"\$(readlink '$DEST')\" = '$ROOT/hermes/skills/loop-runner' ]"

# Someone else's link is not ours to replace — the same refusal install-hermes
# makes for every other skill path.
rm "$DEST"
ln -s "$TMP/somewhere-else" "$DEST"
OUT="$(run 2>&1)"; RC=$?
t "unmanaged link: refuses"         "[ $RC -ne 0 ]"
t "unmanaged link: names it"        "printf '%s' \"\$OUT\" | grep -q 'refusing to replace unmanaged'"
t "unmanaged link: left alone"      "[ \"\$(readlink '$DEST')\" = '$TMP/somewhere-else' ]"

# A real directory there is not ours either.
rm "$DEST"; mkdir -p "$DEST"
OUT="$(run 2>&1)"; RC=$?
t "real directory: refuses"         "[ $RC -ne 0 ]"
t "real directory: left alone"      "[ -d '$DEST' ] && [ ! -L '$DEST' ]"

rm -rf "$TMP"
echo; echo "link-loop-runner.test.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
