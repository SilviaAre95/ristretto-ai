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
| Hermes Agent 0.18.x | The runtime Ris is built on; install and authenticate it separately. |
| A Slack workspace you control | Ris talks through a Slack app you create there. |
| A Linear team | Board-backed briefs and coding tasks. |
| Claude Code (optional) | Default `classic` coding flow; uses your own account. |
| Codex CLI, GitHub CLI (optional) | Review stages in named flows; PR tooling. |

Do you need a local LLM? **Yes, for the orchestrator.** By design, all
orchestration — chat, morning briefs, tool decisions — runs through a local
Ollama model with no cloud calls, so day-to-day operation has zero marginal
model cost (see [`features/local-brain.md`](features/local-brain.md)). The
suggested brain is `qwen3.6:27b`, which realistically wants an Apple Silicon
Mac with 32 GB+ of memory. Coding is a separate axis: the default `classic`
flow uses Claude Code with your own account, so the local coder model is only
needed for the `local`/`balanced` flows or the automatic fallback when Claude
is unavailable.

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
ollama pull qwen3.6:27b        # orchestrator brain (required)
ollama pull qwen3-coder:30b    # local coding model (optional)
```

Override the coding model with `RIS_LOCAL_LOOP_MODEL` in `~/.hermes/.env`.

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

## Telegram ops lane (optional)

Drive real Claude Code on this machine from your phone, gated by Claude Code's
own permission settings.

1. Create a bot with BotFather; put the token in `~/.hermes/.env` as
   `TELEGRAM_BOT_TOKEN`. Set `TELEGRAM_ALLOWED_USERS` to your numeric Telegram ID.
2. Install the optional extra: `pip install -e '.[ops]'`.
3. Set user-level deny rules in `~/.claude/settings.json` (see
   `docs/examples/claude-settings.user.json`) and per-repo rules in each
   repo's `.claude/settings.json` (see `docs/examples/claude-settings.repo.json`).
4. Validate: `ristretto ops-daemon --check`.
5. Run: `ristretto ops-daemon`. Message the bot, name a repo, give it a task.
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
