#!/usr/bin/env bash
# The rename migration, against a fake install.
#
# Two properties matter more than the individual moves. It must be safe to
# run twice, because the first run can fail halfway on a real machine; and it
# must never remove a link this project did not write, because the whole
# reason the migration exists is that the installers' guards refuse to guess.
#
# `hermes` is stubbed. The migration calls it to disable plugins, remove a
# cron job and rename a profile, and none of those should reach a real
# Hermes install from a test.
set -u
PASS=0; FAIL=0
t() { if eval "$2"; then echo "ok  - $1"; PASS=$((PASS+1)); else echo "FAIL - $1"; FAIL=$((FAIL+1)); fi; }

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$ROOT/scripts/migrate-cuzam.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/cuzam-migrate-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

HH="$TMP/hermes"
OLD_STATE="$TMP/.ristretto"
NEW_STATE="$TMP/.cuzam"
OLD_CONFIG="$TMP/config/ristretto"
NEW_CONFIG="$TMP/config/cuzam"
BIN="$TMP/bin"
FAKEBIN="$TMP/fakebin"
CRON_LOG="$TMP/hermes-calls.log"

mkdir -p "$FAKEBIN" "$BIN"
cat > "$FAKEBIN/hermes" <<CRON
#!/usr/bin/env bash
echo "\$*" >> "$CRON_LOG"
case "\$1 \${2:-}" in
  "cron list")
    # Stateful on purpose: a stub that keeps listing a removed job would
    # make the idempotency assertion below pass against a script that
    # removed it twice.
    [ -f "$TMP/cron-removed" ] || \
      printf '  f136dc5839b2 [active]\n    Name:      Ris doorbell\n'
    ;;
  "cron remove")
    : > "$TMP/cron-removed"
    ;;
  "profile rename")
    mv "$HH/profiles/\$3" "$HH/profiles/\$4"
    ;;
  "profile alias")
    printf '#!/bin/sh\nexec hermes -p \$3 "\$@"\n' > "$BIN/\$3"
    chmod +x "$BIN/\$3"
    ;;
esac
exit 0
CRON
chmod +x "$FAKEBIN/hermes"

# The fixture: an install as it looks the moment before the release lands.
build_fixture() {
  rm -rf "$HH" "$OLD_STATE" "$NEW_STATE" "$OLD_CONFIG" "$NEW_CONFIG" "$CRON_LOG" "$TMP/cron-removed"
  mkdir -p "$HH/plugins" "$HH/scripts" "$HH/skills/software-development" \
           "$HH/profiles/ris-worker/node/bin" "$OLD_STATE/runtime/hermes" \
           "$OLD_CONFIG" "$TMP/repo-plugins"
  for name in approvals launch chat; do
    mkdir -p "$TMP/repo-plugins/hermes/plugins/ris-$name"
    ln -s "$TMP/repo-plugins/hermes/plugins/ris-$name" "$HH/plugins/ris-$name"
  done
  ln -s "$OLD_STATE/runtime/hermes/skills/loop-runner" \
    "$HH/skills/software-development/loop-runner"
  for name in ris-stop.sh ris-event.py ris-doorbell.sh; do : > "$HH/scripts/$name"; done
  printf 'approvals\n' > "$OLD_STATE/approvals.db"
  printf 'events\n'    > "$OLD_STATE/events.db"
  printf '7\n'         > "$OLD_STATE/doorbell.cursor"
  printf 'venv\n'      > "$OLD_STATE/runtime/marker"
  printf 'config\n'    > "$OLD_CONFIG/config.yaml"
  : > "$HH/profiles/ris-worker/node/bin/node"
  chmod +x "$HH/profiles/ris-worker/node/bin/node"
  ln -sfn "$HH/profiles/ris-worker/node/bin/node" "$BIN/node"
  printf '#!/bin/sh\nexec hermes -p ris-worker "$@"\n' > "$BIN/ris-worker"
  chmod +x "$BIN/ris-worker"
}

run() {
  PATH="$FAKEBIN:$PATH" \
  CUZAM_HERMES_HOME="$HH" \
  RISTRETTO_STATE_HOME="$OLD_STATE" \
  CUZAM_STATE_HOME="$NEW_STATE" \
  RISTRETTO_CONFIG_DIR="$OLD_CONFIG" \
  CUZAM_CONFIG_DIR="$NEW_CONFIG" \
  CUZAM_BIN_DIR="$BIN" \
  HOME="$TMP" \
    bash "$SCRIPT" "$@"
}

build_fixture
OUT="$(run 2>&1)"; RC=$?

t "succeeds"                        "[ $RC -eq 0 ]"
t "old plugin links are gone"       "[ ! -e '$HH/plugins/ris-approvals' ] && [ ! -L '$HH/plugins/ris-approvals' ]"
t "each plugin was disabled first"  "[ \"\$(grep -c 'plugins disable' '$CRON_LOG')\" -eq 3 ]"
t "loop-runner link is gone"        "[ ! -L '$HH/skills/software-development/loop-runner' ]"
t "old hermes scripts are gone"     "[ ! -e '$HH/scripts/ris-stop.sh' ] && [ ! -e '$HH/scripts/ris-event.py' ]"
t "the old cron job is removed"     "grep -q 'cron remove f136dc5839b2' '$CRON_LOG'"

# The irreplaceable state. runtime/ is the one thing that must NOT survive:
# its venv carries the old absolute path, so a moved copy yields an
# interpreter that starts and a child that dies instantly.
t "approvals.db moved"              "[ -f '$NEW_STATE/approvals.db' ]"
t "events.db moved"                 "[ -f '$NEW_STATE/events.db' ]"
t "doorbell cursor moved"           "[ -f '$NEW_STATE/doorbell.cursor' ]"
t "content survived the move"       "[ \"\$(cat '$NEW_STATE/approvals.db')\" = approvals ]"
t "runtime/ was deleted, not moved" "[ ! -e '$NEW_STATE/runtime' ] && [ ! -e '$OLD_STATE/runtime' ]"
t "the old state home is gone"      "[ ! -d '$OLD_STATE' ]"
t "user config moved"               "[ -f '$NEW_CONFIG/config.yaml' ]"

# The worker profile is renamed in place: it holds the session history, the
# approved-hook fingerprint and a node install three PATH entries point into.
t "profile renamed in place"        "[ -d '$HH/profiles/zam-worker' ] && [ ! -d '$HH/profiles/ris-worker' ]"
t "node link follows the profile"   "[ \"\$(readlink '$BIN/node')\" = '$HH/profiles/zam-worker/node/bin/node' ]"
t "worker wrapper renamed"          "[ -f '$BIN/zam-worker' ] && [ ! -e '$BIN/ris-worker' ]"

# Safe to run twice: the first run can fail halfway on a real machine.
OUT2="$(run 2>&1)"; RC2=$?
t "second run succeeds"             "[ $RC2 -eq 0 ]"
t "second run says it did nothing"  "printf '%s' \"\$OUT2\" | grep -q 'nothing left to migrate'"
t "second run kept the state"       "[ -f '$NEW_STATE/approvals.db' ]"

# A link the user put there is not ours to remove. This is the whole reason
# the installers refuse rather than replace, and the migration must not be
# the thing that quietly overrides them.
build_fixture
rm "$HH/skills/software-development/loop-runner"
ln -s "$TMP/somewhere-else" "$HH/skills/software-development/loop-runner"
rm "$HH/plugins/ris-chat"
ln -s "$TMP/somewhere-else" "$HH/plugins/ris-chat"
OUT3="$(run 2>&1)"; RC3=$?
t "unmanaged links: still succeeds"  "[ $RC3 -eq 0 ]"
t "unmanaged loop-runner kept"       "[ -L '$HH/skills/software-development/loop-runner' ]"
t "unmanaged plugin link kept"       "[ -L '$HH/plugins/ris-chat' ]"
t "unmanaged links are reported"     "printf '%s' \"\$OUT3\" | grep -q 'we did not write'"
t "managed links still removed"      "[ ! -L '$HH/plugins/ris-approvals' ]"

echo; echo "migrate-cuzam.test.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
