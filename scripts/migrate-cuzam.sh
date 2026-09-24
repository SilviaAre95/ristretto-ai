#!/usr/bin/env bash
# One-time migration from the Ristretto/Nemo names to Cuzam/Zam.
#
# This moves the things that live outside the checkout, which the installers
# deliberately cannot move for themselves. Both link guards refuse to replace
# a path they did not just create, and that is correct — it is also exactly
# why they cannot do this:
#
#   - `link_skill` (install-hermes.sh) returns 0 only when the destination is
#     already a link to the exact source it wants. The plugins' destination
#     *names* change, so `ln -s` succeeds for the new ones and the old
#     `~/.hermes/plugins/ris-*` links survive — still enabled, pointing at
#     paths that no longer exist.
#   - `link-loop-runner.sh` is the harder one. After `~/.ristretto` ->
#     `~/.cuzam` the existing link matches neither the new repo source nor
#     the new runtime source, so it takes the "refusing to replace unmanaged
#     link" branch and exits 1 — the guard misclassifies this project's own
#     link as the user's.
#
# So the old names are removed here, explicitly, before any installer runs.
#
# Every step is idempotent and re-runnable, and nothing is removed unless it
# is recognisably ours: a link pointing somewhere this project never wrote is
# left alone and reported, which is what the guards exist for. Run it twice
# and the second run should say only that there was nothing left to do.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
hermes_home="${CUZAM_HERMES_HOME:-${RISTRETTO_HERMES_HOME:-${HERMES_HOME:-$HOME/.hermes}}}"
# eval so a configured ~ expands the way events.state_home() expands it with
# .expanduser(), the same reason install-runtime.sh does it.
eval old_state="${RISTRETTO_STATE_HOME:-$HOME/.ristretto}"
eval new_state="${CUZAM_STATE_HOME:-$HOME/.cuzam}"
old_config="${RISTRETTO_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/ristretto}"
new_config="${CUZAM_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/cuzam}"
bin_dir="${CUZAM_BIN_DIR:-${RISTRETTO_BIN_DIR:-$HOME/.local/bin}}"

did_something=0
step() { printf '\n%s\n' "$1"; }
say()  { printf '  %s\n' "$1"; }
done_() { did_something=1; printf '  %s\n' "$1"; }
warn() { printf '  ! %s\n' "$1" >&2; }

hermes_() { HERMES_HOME="$hermes_home" hermes "$@"; }

# Refuse while a run is live, before anything moves. Every step below is
# hostile to a run in flight: it unlinks the skill the classic loop is
# executing and moves the event store it is writing to. live-runs.sh matches
# the old module name as well as the new one, so a flow started before the
# release still counts.
if live="$(bash "$repo/scripts/live-runs.sh")"; then
  echo "migrate: refusing while a run is live" >&2
  printf '  %s\n' "$live" >&2
  echo "  this moves state and unlinks skills under it — stop it, or wait" >&2
  exit 1
fi

echo "Migrating Ristretto -> Cuzam."
echo "  Hermes home:  $hermes_home"
echo "  state:        $old_state -> $new_state"
echo "  user config:  $old_config -> $new_config"

# --------------------------------------------------------------- plugins

step "Hermes plugins (ris-* -> zam-*)"
for name in approvals launch chat; do
  link="$hermes_home/plugins/ris-$name"
  if [ ! -e "$link" ] && [ ! -L "$link" ]; then
    say "ris-$name: already gone"
    continue
  fi
  if [ ! -L "$link" ]; then
    warn "ris-$name: not a symlink, left alone: $link"
    continue
  fi
  target="$(readlink "$link")"
  case "$target" in
    */hermes/plugins/ris-$name) ;;
    *)
      warn "ris-$name: link we did not write, left alone -> $target"
      continue
      ;;
  esac
  # Disabling first: a plugin directory that vanishes under an enabled
  # registration is how `!ris-approve` ends up registered and broken rather
  # than simply absent.
  hermes_ plugins disable "ris-$name" >/dev/null 2>&1 || true
  rm "$link"
  done_ "ris-$name: disabled and unlinked"
done

# ----------------------------------------------------------- loop-runner

step "loop-runner skill link"
dest="$hermes_home/skills/software-development/loop-runner"
if [ -L "$dest" ]; then
  target="$(readlink "$dest")"
  case "$target" in
    "$repo/hermes/skills/loop-runner" \
    |"$old_state/runtime/hermes/skills/loop-runner" \
    |"$new_state/runtime/hermes/skills/loop-runner")
      rm "$dest"
      done_ "unlinked (was -> $target)"
      ;;
    *)
      warn "link we did not write, left alone -> $dest -> $target"
      warn "remove it by hand if it is stale; install-hermes.sh will refuse otherwise"
      ;;
  esac
elif [ -e "$dest" ]; then
  warn "not a symlink, left alone: $dest"
else
  say "already gone"
fi

# -------------------------------------------------------- hermes scripts

step "Hermes scripts (copies, not links)"
for name in ris-stop.sh ris-event.py ris-doorbell.sh; do
  path="$hermes_home/scripts/$name"
  if [ -e "$path" ]; then
    rm "$path"
    done_ "removed $name"
  else
    say "$name: already gone"
  fi
done

# ------------------------------------------------------------ doorbell cron

step "Doorbell cron job"
# The job is found by name and removed by id. Renaming the script would leave
# the old job running the copy just deleted, failing every two minutes.
job_id="$(hermes_ cron list --all 2>/dev/null | awk '
  /^  [0-9a-f]{12} \[/ { id = $1 }
  /^    Name: +Ris doorbell$/ { print id; exit }
')"
if [ -n "$job_id" ]; then
  hermes_ cron remove "$job_id" >/dev/null
  done_ "removed the 'Ris doorbell' job ($job_id); install-hermes.sh creates 'Zam doorbell'"
else
  say "no 'Ris doorbell' job"
fi

# ---------------------------------------------------------- worker profile

step "Worker profile (ris-worker -> zam-worker)"
# Renamed in place rather than recreated. The directory carries the agent's
# session history, the approved-hook fingerprint for loop-flow-guard.sh, an
# LSP cache and a node installation that ~/.local/bin/{node,npm,npx} point
# into — a fresh profile would silently drop all four.
if [ -d "$hermes_home/profiles/zam-worker" ]; then
  say "zam-worker already exists"
elif [ -d "$hermes_home/profiles/ris-worker" ]; then
  hermes_ profile rename ris-worker zam-worker >/dev/null
  done_ "renamed the profile"
else
  say "no ris-worker profile; install-hermes.sh will create zam-worker"
fi

# The wrapper script and the three node links are outside Hermes' own
# bookkeeping, so they are repointed here whether or not the rename just ran.
old_node="$hermes_home/profiles/ris-worker/node/bin"
new_node="$hermes_home/profiles/zam-worker/node/bin"
for name in node npm npx; do
  link="$bin_dir/$name"
  [ -L "$link" ] || continue
  target="$(readlink "$link")"
  case "$target" in
    "$old_node/$name")
      if [ -x "$new_node/$name" ]; then
        ln -sfn "$new_node/$name" "$link"
        done_ "repointed $name -> $new_node/$name"
      else
        warn "$name still points into the old profile and the new one has no node"
        warn "  left alone: $link -> $target"
      fi
      ;;
  esac
done

if [ -f "$bin_dir/ris-worker" ]; then
  hermes_ profile alias zam-worker >/dev/null 2>&1 || true
  if [ -f "$bin_dir/zam-worker" ]; then
    rm "$bin_dir/ris-worker"
    done_ "replaced the ris-worker wrapper with zam-worker"
  else
    warn "could not create a zam-worker wrapper; left $bin_dir/ris-worker alone"
  fi
fi

# ------------------------------------------------------------------- state

step "State home"
if [ -d "$old_state" ]; then
  mkdir -p "$new_state"
  for path in "$old_state"/* "$old_state"/.[!.]*; do
    [ -e "$path" ] || continue
    name="$(basename "$path")"
    # runtime/ is deleted, never moved. Its venv carries the old absolute
    # path in shebangs and pyvenv.cfg, so a moved copy yields an interpreter
    # Popen accepts and a child that dies instantly — a failure that reads
    # like the flow, not like the move. `make install-runtime` rebuilds it.
    if [ "$name" = "runtime" ]; then
      rm -rf "$path"
      done_ "deleted runtime/ (rebuilt by make install-runtime, never moved)"
      continue
    fi
    if [ -e "$new_state/$name" ]; then
      warn "$name already exists in $new_state, left the old copy at $path"
      continue
    fi
    mv "$path" "$new_state/$name"
    done_ "moved $name"
  done
  rmdir "$old_state" 2>/dev/null && done_ "removed $old_state" || \
    say "left $old_state in place (not empty)"
else
  say "no $old_state"
fi

# ------------------------------------------------------------ user config

step "User configuration"
if [ -d "$old_config" ] && [ ! -e "$new_config" ]; then
  mkdir -p "$(dirname "$new_config")"
  mv "$old_config" "$new_config"
  done_ "moved $old_config -> $new_config"
elif [ -d "$old_config" ]; then
  warn "both $old_config and $new_config exist; left the old one alone"
else
  say "nothing to move"
fi

# --------------------------------------------------------------- CLI links

step "CLI links"
for name in ristretto nemo; do
  link="$bin_dir/$name"
  [ -L "$link" ] || continue
  target="$(readlink "$link")"
  case "$target" in
    "$repo/.venv/bin/$name")
      rm "$link"
      done_ "removed the stale $name link (the console script still exists for one release)"
      ;;
    *) warn "$name -> $target is not ours, left alone" ;;
  esac
done

# ----------------------------------------------------------------- launchd

step "Dashboard service"
old_label="com.ristretto.dash"
old_plist="$HOME/Library/LaunchAgents/$old_label.plist"
if [ -f "$old_plist" ]; then
  launchctl bootout "gui/$(id -u)/$old_label" 2>/dev/null || true
  rm "$old_plist"
  done_ "unloaded and removed $old_label"
  say "re-install with: make install-dash-service  (label is now com.cuzam.dash)"
else
  say "no $old_label plist"
fi

# ---------------------------------------------------------------- SOUL.md

step "Persona"
# Replaced only when the live copy is untouched. `.template-seeds` records
# the hash of the template each user-owned file was seeded from, and the copy
# was byte-identical at that moment — so a live file still matching its seed
# has never been edited, and can be moved to the renamed template safely.
seeds="$hermes_home/.template-seeds"
live_soul="$hermes_home/SOUL.md"
hash_of() { shasum -a 256 "$1" | awk '{print $1}'; }
if [ ! -f "$live_soul" ]; then
  say "no SOUL.md yet; install-hermes.sh will seed the renamed one"
elif [ ! -f "$seeds" ]; then
  warn "no seed record, so an edit cannot be ruled out — left SOUL.md alone"
  warn "  Zam will keep introducing itself as Nemo until you port it:"
  warn "  diff \"$live_soul\" \"$repo/hermes/SOUL.md\""
else
  recorded="$(awk '$1 == "SOUL.md" { print $2 }' "$seeds")"
  if [ -n "$recorded" ] && [ "$(hash_of "$live_soul")" = "$recorded" ]; then
    cp "$repo/hermes/SOUL.md" "$live_soul"
    chmod 0600 "$live_soul"
    # Re-record, or template-drift.sh reports the rename as drift forever.
    bash "$repo/scripts/template-drift.sh" --ack >/dev/null
    done_ "SOUL.md was unmodified — replaced with the renamed persona"
  else
    warn "SOUL.md has been edited, so it was left alone"
    warn "  Zam will keep introducing itself as Nemo until you port it:"
    warn "  diff \"$live_soul\" \"$repo/hermes/SOUL.md\""
  fi
fi

# ------------------------------------------------------------------- done

step "Done."
if [ "$did_something" -eq 0 ]; then
  say "nothing left to migrate — this install is already on the new names"
fi
cat <<'NEXT'

  Next, in this order:
    make install-runtime   # rebuilds the runtime that was just deleted
    make update            # reinstalls assets and restarts the gateway

  Two things this cannot do for you:
    - the microphone grant, revoked by the bundle id change; macOS asks again
    - the Slack manifest, inert until re-uploaded by hand
NEXT
