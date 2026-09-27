#!/usr/bin/env bash
# The rename migration, against a fake install.
#
# Three properties matter more than the individual moves. It must refuse
# while a coding run is live, because every step below is hostile to a run in
# flight; it must be safe to run twice, because the first run can fail halfway
# on a real machine; and it must never remove a link this project did not
# write, because the whole reason the migration exists is that the installers'
# guards refuse to guess.
#
# `hermes` is stubbed. The migration calls it to disable plugins, remove a
# cron job and rename a profile, and none of those should reach a real
# Hermes install from a test.
set -u
PASS=0; FAIL=0
t() { if eval "$2"; then echo "ok  - $1"; PASS=$((PASS+1)); else echo "FAIL - $1"; FAIL=$((FAIL+1)); fi; }

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# `pwd -P` and not just mktemp's answer. On macOS $TMPDIR is /var/folders/...,
# and the migration resolves its own repository with `cd "$(dirname ...)/.." &&
# pwd`, which reports /private/var — so the two would be different strings for
# one directory. That is harmless for the fixture as it stands and a trap for
# the next step added to it: the managed-link branches compare `readlink`
# output against "$repo/hermes/skills/loop-runner" and "$repo/.venv/bin/...",
# so a fixture built with the unresolved path takes the "link we did not write"
# branch while appearing to cover the managed one.
TMP="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/cuzam-migrate-test.XXXXXX")" && pwd -P)"
trap 'rm -rf "$TMP"' EXIT

# The migration is run from a COPY of scripts/, and that is the only reason
# this file is hermetic.
#
# Its first act is to refuse while a coding run is live, and it asks
# scripts/live-runs.sh — which snapshots `ps -eo pid=,command=` and filters,
# deliberately never `pgrep`, for the reasons its own comments give. So it
# reads the real machine, and no variable this test sets can reach it: with a
# real Cuzam run alive on the developer's box, 26 of the 33 assertions below
# used to fail, on code that passes 33/33 on a quiet one.
#
# The guard is right — the migration moves the event store out from under a
# running flow — so nothing about it is weakened here. The seam is that the
# migration resolves its own repository from ${BASH_SOURCE[0]} and calls
# "$repo/scripts/live-runs.sh". Run the real script from a fake repository and
# the probe it consults is ours, while a real machine has no way to reach the
# stub: there is no override variable, and nothing in scripts/ changed.
#
# Copied rather than symlinked, and that is not fussiness. Writing the stub
# through a symlink truncates the real scripts/live-runs.sh in the checkout.
REPO="$TMP/repo"
mkdir -p "$REPO"
cp -R "$ROOT/scripts" "$REPO/scripts"
# Only scripts/. The migration's other repo-relative reads are $repo/.venv and
# $repo/hermes/SOUL.md, and both are on branches this fixture never reaches —
# .venv only as a string compared against a readlink, SOUL.md only when
# $hermes_home/.template-seeds exists, which build_fixture does not create. An
# earlier draft linked hermes/ in "so it stays reachable", which handed the
# fake repo a writable handle on the real checkout: the same hazard as the
# paragraph above, one directory over. A future step that needs those paths
# copies them the way scripts/ is copied.
SCRIPT="$REPO/scripts/migrate-cuzam.sh"

# The two answers the stub can give. Both are about what the MACHINE looks
# like, which is exactly the input this file could not previously control.
# Each stub records that it ran, and that record is asserted below. Writing a
# stub is not the same as the migration reading it: rename scripts/live-runs.sh
# and the call site together and the stub lands at a path nobody consults, the
# migration falls through to the copied real probe, and this file silently
# resumes reading host processes — green on a quiet machine, 26 failures on a
# busy one, with nothing to say which happened. The quiet-machine assertion
# cannot catch that, because it passes identically either way.
PROBED="$TMP/probe-consulted"
STUB="$REPO/scripts/live-runs.sh"
# `rm -f` first, every time, and the reason is the accident in the paragraph
# above rather than tidiness. `>` follows a symlink, and `cp -R` copies a
# symlink AS a symlink — so the day scripts/live-runs.sh becomes one in the
# checkout, or someone makes this fixture cheaper with `cp -Rs`, the redirect
# truncates a tracked file in the developer's working tree again. Unlinking
# first cannot do that, and the assertion below makes the property checked
# rather than merely intended.
write_stub() {
  rm -f "$STUB"
  printf '%s' "$1" > "$STUB"
  chmod +x "$STUB"
}
quiet_machine() {
  write_stub "$(printf '#!/usr/bin/env bash\n: > "%s"\nexit 1\n' "$PROBED")"
}
live_run() {
  write_stub "$(printf '#!/usr/bin/env bash\n: > "%s"\n%s\nexit 0\n' "$PROBED" \
    'echo "4242 bash /x/loop-runner/scripts/run-loop.sh t_live000 ABC-1 --flow classic"')"
}
quiet_machine
t "the stub is a real file, not a link" "[ -f '$STUB' ] && [ ! -L '$STUB' ]"

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
  rm -f "$PROBED"
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

# State already under the new name is fatal, and fatal BEFORE anything
# moves. This is not hypothetical: `make check` used to leave an empty
# approvals.db and events.db in the real state home, because the dashboard
# route tests rendered the fleet without overriding it. Warning and carrying
# on would have stranded the real databases and brought the install up on the
# empty pair, with every surface agreeing nothing had ever happened.
build_fixture
mkdir -p "$NEW_STATE"
printf 'stub\n' > "$NEW_STATE/events.db"
OUT4="$(run 2>&1)"; RC4=$?
t "a state collision fails"          "[ $RC4 -ne 0 ]"
t "it names the colliding file"      "printf '%s' \"\$OUT4\" | grep -q 'events.db'"
t "it shows both sizes"              "printf '%s' \"\$OUT4\" | grep -q 'old .* bytes'"
t "the real state is not stranded"   "[ -f '$OLD_STATE/events.db' ] && [ \"\$(cat '$OLD_STATE/events.db')\" = events ]"
t "the stub is not overwritten"      "[ \"\$(cat '$NEW_STATE/events.db')\" = stub ]"
# Refusing halfway would leave a state home that is neither old nor new.
t "nothing moved before refusing"    "[ -f '$OLD_STATE/approvals.db' ] && [ ! -e '$NEW_STATE/approvals.db' ]"
t "runtime/ survives a refusal"      "[ -d '$OLD_STATE/runtime' ]"

# Resolve it the way the message says, and the migration completes.
rm "$NEW_STATE/events.db"
OUT5="$(run 2>&1)"; RC5=$?
t "resolving the collision unblocks" "[ $RC5 -eq 0 ]"
t "the real events.db then moves"    "[ \"\$(cat '$NEW_STATE/events.db')\" = events ]"

# The guard itself. Untestable before the fake repository existed, which is
# why the first thing the migration does was also the only thing this file
# never checked. It has to refuse BEFORE anything moves: a migration that
# unlinks the skill a classic loop is executing and then notices the loop has
# already broken it.
build_fixture
live_run
OUT6="$(run 2>&1)"; RC6=$?
quiet_machine
t "a live run blocks the migration"  "[ $RC6 -ne 0 ]"
t "the live run is named"            "printf '%s' \"\$OUT6\" | grep -q 'run-loop.sh'"
t "it says why it refused"           "printf '%s' \"\$OUT6\" | grep -q 'refusing while a run is live'"
t "nothing moved while live"         "[ -f '$OLD_STATE/approvals.db' ] && [ ! -e '$NEW_STATE/approvals.db' ]"
t "no link was removed while live"   "[ -L '$HH/plugins/ris-approvals' ]"
t "the profile was not renamed"      "[ -d '$HH/profiles/ris-worker' ] && [ ! -d '$HH/profiles/zam-worker' ]"

# And a quiet machine still migrates, so the assertion above is about the
# guard rather than about the stub being consulted at all.
OUT7="$(run 2>&1)"; RC7=$?
t "a quiet machine then migrates"    "[ $RC7 -eq 0 ] && [ -f '$NEW_STATE/approvals.db' ]"

# The stub, not the real probe, is what answered. Everything above rests on
# this one assertion, so it is stated rather than assumed.
t "the stubbed probe was consulted"  "[ -f '$PROBED' ]"

echo; echo "migrate-cuzam.test.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
