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

install -m 0755 \
  "$repo/hermes/scripts/morning-brief-precheck.py" \
  "$hermes_home/scripts/morning-brief-precheck.py"
install -m 0755 \
  "$repo/hermes/scripts/ris-stop.sh" \
  "$hermes_home/scripts/ris-stop.sh"

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
HERMES_HOME="$hermes_home" hermes -p ris-worker config set model.default qwen3.6:27b >/dev/null
HERMES_HOME="$hermes_home" hermes -p ris-worker config set model.base_url http://localhost:11434/v1 >/dev/null
HERMES_HOME="$hermes_home" hermes -p ris-worker config set agent.max_turns 300 >/dev/null
HERMES_HOME="$hermes_home" hermes -p ris-worker config set tool_loop_guardrails.hard_stop_enabled true >/dev/null
HERMES_HOME="$hermes_home" hermes -p ris-worker config set session_reset.idle_minutes 180 >/dev/null

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
