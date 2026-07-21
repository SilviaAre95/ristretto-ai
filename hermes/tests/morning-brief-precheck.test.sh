#!/usr/bin/env bash
set -u
PASS=0; FAIL=0
t() { if eval "$2"; then echo "ok  - $1"; PASS=$((PASS+1)); else echo "FAIL - $1"; FAIL=$((FAIL+1)); fi; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/scripts/morning-brief-precheck.py"
PYTHON="${PYTHON:-python3}"
TMP="$(mktemp -d)"
STATE="$TMP/state.json"
FIXTURE="$TMP/issues.json"

cat > "$FIXTURE" <<'EOF'
{"issues":[
  {"id":"1","url":"https://linear.app/demo/issue/PROJ-1/first","title":"First issue","project":"Example App","status":"Todo","statusType":"unstarted","priority":{"value":2,"name":"High"},"updatedAt":"2026-07-17T10:00:00Z"},
  {"id":"2","url":"https://linear.app/demo/issue/PROJ-2/second","title":"Second issue","project":"Example App","status":"Done","statusType":"completed","priority":{"value":1,"name":"Urgent"},"updatedAt":"2026-07-17T10:00:00Z"}
]}
EOF

FIRST="$TMP/first.txt"
"$PYTHON" "$SCRIPT" --fixture "$FIXTURE" --state-file "$STATE" > "$FIRST"
t "first run reports initial snapshot" "grep -q 'Initial snapshot: 1 open issues' '$FIRST'"
t "closed issues are excluded"         "! grep -q 'PROJ-2' '$FIRST'"
t "signal includes high issue"         "grep -q 'PROJ-1 | Example App | High' '$FIRST'"
t "state file is persisted"            "[ -s '$STATE' ]"

SECOND="$TMP/second.txt"
"$PYTHON" "$SCRIPT" --fixture "$FIXTURE" --state-file "$STATE" > "$SECOND"
t "unchanged board is exactly silent"  "[ \"\$(cat '$SECOND')\" = 'NO_CHANGES' ]"

sed 's/First issue/First issue changed/;s/10:00:00/11:00:00/' "$FIXTURE" > "$TMP/changed.json"
CHANGED="$TMP/changed.txt"
"$PYTHON" "$SCRIPT" --fixture "$TMP/changed.json" --state-file "$STATE" > "$CHANGED"
t "changed issue is reported"          "grep -q 'Updated: PROJ-1.*First issue changed' '$CHANGED'"

printf '%s\n' '{"issues":[]}' > "$TMP/empty.json"
REMOVED="$TMP/removed.txt"
"$PYTHON" "$SCRIPT" --fixture "$TMP/empty.json" --state-file "$STATE" > "$REMOVED"
t "issue leaving open board is reported" "grep -q 'Left open board: PROJ-1' '$REMOVED'"
t "empty signal is explicit"             "grep -A1 'CURRENT URGENT' '$REMOVED' | grep -q -- '- None'"

echo; echo "morning-brief-precheck.test.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
