#!/usr/bin/env bash
# Install Ristretto's public Hermes assets without overwriting user-owned
# config, persona, credentials, jobs, or unrelated skills.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
hermes_home="${RISTRETTO_HERMES_HOME:-${HERMES_HOME:-$HOME/.hermes}}"
install_service=0

if [ "${1:-}" = "--service" ]; then
  install_service=1
elif [ "$#" -gt 0 ]; then
  echo "install-hermes: usage: scripts/install-hermes.sh [--service]" >&2
  exit 2
fi

command -v hermes >/dev/null || {
  echo "install-hermes: hermes is required; install Hermes Agent first" >&2
  exit 1
}
command -v ristretto >/dev/null || {
  echo "install-hermes: ristretto CLI is required; run make install first" >&2
  exit 1
}

ristretto validate
linear_team="$(ristretto instance get linear_team)" || exit 1
home_channel="$(ristretto instance get slack_home_channel)" || exit 1
ristretto instance get slack_prs_channel >/dev/null
ristretto instance get slack_alerts_channel >/dev/null

mkdir -p "$hermes_home" "$hermes_home/scripts" \
  "$hermes_home/skills/software-development"

# Record which template version seeded each user-owned copy, so
# scripts/template-drift.sh can flag upstream template changes on update.
# Existing installs without a record are baselined on the current template.
seed_record="$hermes_home/.template-seeds"
record_seed() {
  local name="$1"
  if [ -f "$seed_record" ] && grep -q "^$name " "$seed_record"; then
    return 0
  fi
  echo "$name $(shasum -a 256 "$repo/hermes/$name" | awk '{print $1}')" \
    >> "$seed_record"
  chmod 0600 "$seed_record"
}

if [ ! -e "$hermes_home/config.yaml" ]; then
  cp "$repo/hermes/config.yaml" "$hermes_home/config.yaml"
  chmod 0600 "$hermes_home/config.yaml"
  echo "Created Hermes config: $hermes_home/config.yaml"
else
  echo "Kept existing Hermes config: $hermes_home/config.yaml"
fi
record_seed "config.yaml"

if [ ! -e "$hermes_home/SOUL.md" ]; then
  cp "$repo/hermes/SOUL.md" "$hermes_home/SOUL.md"
  chmod 0600 "$hermes_home/SOUL.md"
  echo "Created Hermes persona: $hermes_home/SOUL.md"
else
  echo "Kept existing Hermes persona: $hermes_home/SOUL.md"
fi
record_seed "SOUL.md"

link_skill() {
  local source="$1"
  local destination="$2"
  if [ -L "$destination" ] && [ "$(readlink "$destination")" = "$source" ]; then
    return 0
  fi
  if [ -e "$destination" ] || [ -L "$destination" ]; then
    echo "install-hermes: refusing to replace existing skill path: $destination" >&2
    exit 1
  fi
  ln -s "$source" "$destination"
}

for skill in durable-dev issue-closeout loop-runner; do
  link_skill \
    "$repo/hermes/skills/$skill" \
    "$hermes_home/skills/software-development/$skill"
done

# Linked, not copied, so the answering path cannot drift from the store it
# writes to. A plugin that disagrees with the CLI about what "approve" means
# is worse than no plugin.
mkdir -p "$hermes_home/plugins"
link_skill \
  "$repo/hermes/plugins/ris-approvals" \
  "$hermes_home/plugins/ris-approvals"
# Linking is not enabling: a discovered plugin sits at "not enabled" and its
# commands never register, so !ris-approve silently does nothing. Enabling is
# idempotent and safe to repeat.
if ! HERMES_HOME="$hermes_home" hermes plugins list 2>/dev/null \
     | grep -q "ris-approvals.*enabled"; then
  HERMES_HOME="$hermes_home" hermes plugins enable ris-approvals >/dev/null 2>&1 || true
fi

install -m 0755 \
  "$repo/hermes/scripts/morning-brief-precheck.py" \
  "$hermes_home/scripts/morning-brief-precheck.py"
install -m 0755 \
  "$repo/hermes/scripts/ris-stop.sh" \
  "$hermes_home/scripts/ris-stop.sh"
install -m 0755 \
  "$repo/hermes/scripts/ris-event.py" \
  "$hermes_home/scripts/ris-event.py"
mkdir -p "$hermes_home/agent-hooks"
# Copy only when it differs. Hermes fingerprints an approved hook script, so
# rewriting an identical copy would invalidate the approval on every install
# and leave the guard needing re-approval it did not actually need.
if ! cmp -s "$repo/hermes/agent-hooks/loop-flow-guard.sh" \
            "$hermes_home/agent-hooks/loop-flow-guard.sh"; then
  install -m 0755 \
    "$repo/hermes/agent-hooks/loop-flow-guard.sh" \
    "$hermes_home/agent-hooks/loop-flow-guard.sh"
fi
install -m 0755 \
  "$repo/hermes/scripts/ris-doorbell.sh" \
  "$hermes_home/scripts/ris-doorbell.sh"

if [ ! -d "$hermes_home/profiles/ris-worker" ]; then
  HERMES_HOME="$hermes_home" hermes profile create ris-worker --no-skills \
    --description "Detached supervised coding worker" >/dev/null
fi
profile_skills="$hermes_home/profiles/ris-worker/skills/software-development"
mkdir -p "$profile_skills"
for skill in durable-dev loop-runner; do
  link_skill "$repo/hermes/skills/$skill" "$profile_skills/$skill"
done

HERMES_HOME="$hermes_home" hermes -p ris-worker config set model.provider custom >/dev/null
HERMES_HOME="$hermes_home" hermes -p ris-worker config set model.default qwen3.6:35b-mlx >/dev/null
HERMES_HOME="$hermes_home" hermes -p ris-worker config set model.base_url http://localhost:11434/v1 >/dev/null
HERMES_HOME="$hermes_home" hermes -p ris-worker config set agent.max_turns 300 >/dev/null
HERMES_HOME="$hermes_home" hermes -p ris-worker config set tool_loop_guardrails.hard_stop_enabled true >/dev/null
HERMES_HOME="$hermes_home" hermes -p ris-worker config set session_reset.idle_minutes 180 >/dev/null
# The terminal tool returns control when it times out, and the default 180s is
# far shorter than a loop. That leaves the worker "waiting" for its own flow —
# which depends on the model choosing to wait, and one did not: it sat for 43
# minutes, then ended its turn and killed the running build with it. A blocking
# call cannot be abandoned, so the worker blocks and the task's own max-runtime
# stays the real bound.
HERMES_HOME="$hermes_home" hermes -p ris-worker config set terminal.timeout 7200 >/dev/null
# Hooks are per profile, and the worker profile is the one that calls
# kanban_complete — declaring the guard only in the top-level config would
# leave the process it exists to gate completely ungated.
#
# Written as a delimited block rather than via `config set`, which stores a
# JSON argument as a *string*: the profile ends up with
#   hooks: {pre_tool_call: '[{...}]'}
# which loads as no hooks at all. That silently disarmed the guard on every
# reinstall, and nothing said so.
profile_config="$hermes_home/profiles/ris-worker/config.yaml"
python3 - "$profile_config" <<'GUARD'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text() if path.exists() else ""
begin, end = "# ris:flow-guard begin", "# ris:flow-guard end"

if begin in text and end in text:
    head, _, rest = text.partition(begin)
    _, _, tail = rest.partition(end)
    text = head.rstrip("\n") + "\n" + tail.lstrip("\n")

# Drop any earlier hooks mapping, children included. Removing only the
# top-level keys orphans their indented entries and leaves YAML that will
# not parse — which is how this went wrong the first time.
kept, dropping = [], False
for line in text.splitlines():
    top_level = line[:1] not in (" ", "\t") and line.strip()
    if top_level and line.split(":", 1)[0] in ("hooks", "hooks_auto_accept"):
        dropping = True
        continue
    if dropping:
        if not line.strip() or not top_level:
            continue
        dropping = False
    kept.append(line)
text = "\n".join(kept)

block = f"""{begin}
hooks:
  pre_tool_call:
    - matcher: "kanban_complete"
      command: "~/.hermes/agent-hooks/loop-flow-guard.sh"
      timeout: 15
# The worker has no TTY to consent at.
hooks_auto_accept: true
{end}
"""
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(text.rstrip("\n") + "\n" + block)
GUARD

# Configuring is not the same as working: prove the guard is actually
# registered rather than trusting that writing the file was enough.
if ! HERMES_HOME="$hermes_home" hermes -p ris-worker hooks list 2>/dev/null \
     | grep -q "loop-flow-guard"; then
  echo "install-hermes: the loop flow guard is not registered on the ris-worker profile" >&2
  echo "  a worker could complete a task without running its loop — refusing to finish silently" >&2
  exit 1
fi
# Hermes fingerprints an approved hook script, so reinstalling a changed copy
# reports "modified since approval". Approval is granted when an agent starts,
# not by any hooks subcommand, so it cannot be refreshed from here — say so
# rather than leaving the operator to find out from a worker that skipped its
# loop. Do not "fix" this by revoking: that disarms the hook outright until an
# agent runs again.
if HERMES_HOME="$hermes_home" hermes -p ris-worker hooks doctor 2>/dev/null \
   | grep -q "modified since approval"; then
  echo "Loop flow guard needs re-approval after this update. Run once:" >&2
  echo "  hermes -p ris-worker --accept-hooks -z ok" >&2
else
  echo "Loop flow guard armed on the ris-worker profile."
fi

# The doorbell turns pipeline milestones into Slack messages. Run as a cron
# rather than a daemon: a missed tick delivers late, a crashed daemon delivers
# never, and the cursor makes catching up free.
if ! HERMES_HOME="$hermes_home" hermes cron list --all | grep -Fq "Ris doorbell"; then
  HERMES_HOME="$hermes_home" hermes cron create "*/2 * * * *" "[SILENT]" \
    --name "Ris doorbell" \
    --script "ris-doorbell.sh" >/dev/null
  echo "Created Ris doorbell cron job."
else
  echo "Kept existing Ris doorbell cron job."
fi

if ! HERMES_HOME="$hermes_home" hermes cron list --all | grep -Fq "Morning brief"; then
  prompt="Use the precheck output as the authoritative $linear_team board snapshot. If it is exactly NO_CHANGES, reply exactly [SILENT]. Otherwise write a short priority-led morning brief and ask what the user wants to work on. Do not mutate Linear."
  HERMES_HOME="$hermes_home" hermes cron create "0 8 * * *" "$prompt" \
    --name "Morning brief" \
    --deliver "slack:$home_channel" \
    --script "morning-brief-precheck.py" >/dev/null
  echo "Created Morning brief cron job."
else
  echo "Kept existing Morning brief cron job."
fi

if [ "$install_service" -eq 1 ]; then
  HERMES_HOME="$hermes_home" hermes gateway install --start-now --start-on-login
else
  echo "Gateway service unchanged. Re-run with --service to install/start it."
fi

echo "Ristretto Hermes assets installed. Run: ristretto doctor"
