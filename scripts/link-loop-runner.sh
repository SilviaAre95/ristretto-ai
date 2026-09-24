#!/usr/bin/env bash
# Point the loop-runner skill at the pinned runtime when there is one.
#
# Every other skill is a symlink into the working checkout, and that is right:
# they are read by an agent you are watching, and drift between a skill and
# the CLI is the thing worth avoiding. loop-runner is different. It is a skill
# by filing and a runtime by behaviour — `run-loop.sh` IS the classic loop, an
# hour of unattended execution, and a symlink into the working checkout means
# that hour runs whatever branch happens to be out and whatever edit was
# half-finished when it started.
#
# That is the exact problem ristretto/runtime.py was written to solve, and it
# solved it for the Python half only: launch.py hands the staged runner a
# pinned interpreter, but the classic path never touches Python, so nothing
# pinned it. This closes that hole by pointing the skill itself at
# ~/.ristretto/runtime, so `make install-runtime` moves the classic and staged
# paths together and flow.json's recorded commit is true for both.
#
# Falls back to the working checkout when no runtime is pinned yet, because a
# fresh install must still work; it says which one it chose.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
hermes_home="${RISTRETTO_HERMES_HOME:-${HERMES_HOME:-$HOME/.hermes}}"
# eval so a configured ~ expands the way events.state_home() expands it, the
# same reason install-runtime.sh does it.
eval runtime="${RISTRETTO_STATE_HOME:-$HOME/.ristretto}/runtime"

destination="$hermes_home/skills/software-development/loop-runner"
repo_source="$repo/hermes/skills/loop-runner"
runtime_source="$runtime/hermes/skills/loop-runner"

# Probe the script itself, not the directory: a half-cloned runtime has the
# tree without the file, and linking to that breaks every classic run.
if [ -f "$runtime_source/scripts/run-loop.sh" ]; then
  desired="$runtime_source"
  note="pinned runtime"
else
  desired="$repo_source"
  note="working checkout (no runtime pinned — run make install-runtime)"
fi

if [ -L "$destination" ]; then
  current="$(readlink "$destination")"
  if [ "$current" = "$desired" ]; then
    echo "loop-runner -> $note"
    exit 0
  fi
  # Only replace a link this project put there. Anything else is the user's
  # and refusing is the whole point of the guard in install-hermes.sh.
  if [ "$current" != "$repo_source" ] && [ "$current" != "$runtime_source" ]; then
    echo "link-loop-runner: refusing to replace unmanaged link: $destination -> $current" >&2
    exit 1
  fi
  rm "$destination"
elif [ -e "$destination" ]; then
  echo "link-loop-runner: refusing to replace existing path: $destination" >&2
  exit 1
fi

mkdir -p "$(dirname "$destination")"
ln -s "$desired" "$destination"
echo "loop-runner -> $note"
