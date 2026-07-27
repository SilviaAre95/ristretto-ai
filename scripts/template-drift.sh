#!/usr/bin/env bash
# Report whether the repo's seeded templates (persona, Hermes config) changed
# upstream since this install's copies were seeded. User-owned files are never
# read, merged, or modified — this only compares template hashes against the
# record written at seed time. `--ack` re-records the current template hashes
# after the user has reviewed (and ported or skipped) the changes.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
hermes_home="${RISTRETTO_HERMES_HOME:-${HERMES_HOME:-$HOME/.hermes}}"
seeds="$hermes_home/.template-seeds"
templates="SOUL.md config.yaml"

hash_of() { shasum -a 256 "$1" | awk '{print $1}'; }

record_all() {
  : > "$seeds"
  for name in $templates; do
    echo "$name $(hash_of "$repo/hermes/$name")" >> "$seeds"
  done
  chmod 0600 "$seeds"
}

if [ "${1:-}" = "--ack" ]; then
  record_all
  echo "template-drift: acknowledged — current template versions recorded"
  exit 0
elif [ "$#" -gt 0 ]; then
  echo "template-drift: usage: scripts/template-drift.sh [--ack]" >&2
  exit 2
fi

if [ ! -d "$hermes_home" ]; then
  echo "template-drift: no Hermes install at $hermes_home — skipped"
  exit 0
fi

if [ ! -f "$seeds" ]; then
  # Install predates seed tracking: baseline on the current templates so
  # FUTURE template changes get flagged (past ones are unknowable here).
  record_all
  echo "template-drift: no seed record found — baselined on current templates"
  exit 0
fi

drift=0
for name in $templates; do
  current="$(hash_of "$repo/hermes/$name")"
  recorded="$(awk -v n="$name" '$1 == n { print $2 }' "$seeds")"
  if [ -z "$recorded" ]; then
    echo "$name $current" >> "$seeds"
    continue
  fi
  if [ "$recorded" != "$current" ]; then
    drift=1
    echo "template-drift: hermes/$name changed upstream since your copy was seeded."
    echo "  Your file is untouched. See the 'Upgrade notes' in CHANGELOG.md, then inspect:"
    echo "    diff \"$hermes_home/$name\" \"$repo/hermes/$name\""
    echo "  After porting what you want (or deciding to skip), acknowledge with:"
    echo "    bash scripts/template-drift.sh --ack"
  fi
done

[ "$drift" -eq 0 ] && echo "template-drift: templates ok"
exit 0
