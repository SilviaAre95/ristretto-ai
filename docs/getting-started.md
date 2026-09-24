# Getting Started

This guide takes you from a fresh clone to a working Ris instance on your own
machine, talking in your own Slack workspace and tracking your own Linear
team. Nothing connects to anyone else's infrastructure: secrets live only in
your `~/.hermes/.env`, and non-secret settings live in
`~/.config/ristretto/config.yaml`.

## What you need

| Requirement | Why |
|---|---|
| macOS | Supported baseline for the always-on `launchd` service path. |
| Python 3.11, Bash 3.2+, Git | Repository tooling and checks. |
| [Ollama](https://ollama.com) | Serves the local orchestrator brain. Required. |
| [Hermes Agent](https://github.com/NousResearch/hermes-agent) 0.18.x | The runtime Ris is built on. Third-party, MIT, by Nous Research — installed and authenticated separately; see below. |
| A Slack workspace you control | Ris talks through a Slack app you create there. |
| A Linear team | Board-backed briefs and coding tasks. |
| Claude Code | Every coding flow runs on it, including the default `full`; uses your own account. Optional only if you never run one. |
| Codex CLI, GitHub CLI (optional) | Review stages in named flows; PR tooling. |

Do you need a local LLM? **Yes, for the orchestrator.** By design, all
orchestration — chat, morning briefs, tool decisions — runs through a local
Ollama model with no cloud calls, so day-to-day operation has zero marginal
model cost (see [`features/local-brain.md`](features/local-brain.md)). The
suggested brain is `qwen3.6:35b-mlx`, which runs on Ollama's MLX engine and
wants an Apple Silicon Mac with more than 32 GB of memory. Coding is a
separate axis and it runs on Claude Code with your own account: no local model
writes, repairs or reviews code, so nothing here needs a large local coder.
That requirement was dropped on 2026-09-23 along with the premise behind it.

### Where Hermes Agent comes from

Ris does not vendor it and does not install it for you. It is
[`hermes-agent`](https://github.com/NousResearch/hermes-agent) by Nous
Research, MIT licensed, published on [PyPI](https://pypi.org/project/hermes-agent/)
and documented at [hermes-agent.nousresearch.com](https://hermes-agent.nousresearch.com/).
Upstream's own installer is the shortest route:

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
hermes --version   # expect 0.18.x
```

Pin the version instead if you would rather not pipe a script into a shell:

```bash
pip install 'hermes-agent==0.18.*'
```

Ris reads the board, sends Slack messages and schedules cron through the
`hermes` CLI as a subprocess — never by importing it — so the version that
matters is the one on your `PATH`. Ris is developed against **0.18.x**. Newer
engines are likely to work, but nothing here gates on the version or contracts
the `kanban --json` shape the fleet view parses, so an upgrade can break that
view quietly. If you install from a git checkout rather than a release,
record any local modifications: an undocumented patch makes your working
configuration unreproducible on the next machine.

## 1. Clone and bootstrap

```bash
git clone https://github.com/SilviaAre95/ristretto-ai
cd ristretto-ai
make setup
source .venv/bin/activate
make check
```

Everything should be green before going further.

## 2. Install the CLI

```bash
make install
ristretto validate
ristretto flow list
```

This only creates `~/.config/ristretto/config.yaml` and a managed CLI
symlink. It never touches Hermes, credentials, or services.

## 3. Pull the local models

```bash
ollama pull qwen3.6:35b-mlx             # orchestrator brain (required)
```

Override the brain with `RIS_LOCAL_BRAIN_MODEL` in `~/.hermes/.env`.

## 4. Create your Slack app

1. Go to <https://api.slack.com/apps> → **Create New App** → **From an app
   manifest** and paste `slack/ristretto-slack-manifest.json` (readable guide:
   [`03-slack-manifest.md`](03-slack-manifest.md)).
2. Copy only the variables you need from `hermes/.env.example` into
   `~/.hermes/.env` — tokens and `SLACK_ALLOWED_USERS` (the allowlist of user
   IDs Ris will obey) belong there and nowhere else.
3. Invite the bot to each channel it will use, via the channel's
   **Integrations → Add apps** tab. The "Add people" dialog does not show
   bots, and an uninvited bot fails silently with `not_in_channel`.

## 5. Configure the instance

```bash
ristretto configure \
  --linear-team PROJ \
  --slack-home-channel YOUR_HOME_CHANNEL_ID \
  --slack-prs-channel YOUR_PRS_CHANNEL_ID \
  --slack-alerts-channel YOUR_ALERTS_CHANNEL_ID \
  --knowledge-vault "$HOME/Notes" \
  --repository "Example App=$HOME/code/example-app"
```

Use Slack channel **IDs**, not `#names` — name resolution only covers
channels the bot has already interacted with. These values are non-secret and
live only in your user configuration.

## 6. Install the Hermes assets

```bash
make install-hermes
```

This adds Ristretto's skills, scripts, and the isolated worker profile to an
existing Hermes installation without overwriting your config, persona,
credentials, jobs, or unrelated skills. The always-on background service is an
explicit opt-in:

```bash
bash scripts/install-hermes.sh --service
```

## 7. Verify

```bash
ristretto doctor
make doctor
```

Then message the bot in your home channel and confirm a reply, a Linear tool
call, and a morning-brief dry run.

## Caveats worth knowing

- The approval gate is verified for explicit approve and deny decisions, but
  its timeout/park-on-no-response behavior is not yet independently verified.
  Do not rely on timeout alone as a safety boundary for unattended risky work.
- Coding workers are deliberately capped at one at a time: two 27B–30B models
  running concurrently can exhaust memory and thermal headroom on most Macs.
- Wake management is your choice: Ristretto never changes `pmset`. If the
  machine sleeps, Ris sleeps with it.

## Updating

When a new release is out, update from your clone with one command:

```bash
make update
```

It pulls the release, refreshes the symlinked skills and scripts, and
restarts the gateway. Your persona (`~/.hermes/SOUL.md`), config,
credentials, and cron jobs are never touched. If the release changed the
persona or config *templates*, the update prints a drift notice with the
diff to review — port what you want, then acknowledge with
`bash scripts/template-drift.sh --ack`. Check the release's **Upgrade
notes** in `CHANGELOG.md` for anything that needs action.

## Where to go next

- [`development.md`](development.md) — contributor environment and checks.
- [`features/INDEX.md`](features/INDEX.md) — behavior contracts and
  non-goals.
- [`features/custom-model-flows.md`](features/custom-model-flows.md) — add
  your own coding flows.
