---
id: telegram-ops-lane
title: Telegram Ops Lane
status: in-progress
created_at: 2026-07-27
last_modified: 2026-07-28
owner: project
depends_on: []
acceptance_criteria:
  - A dedicated daemon owns one identity-locked Telegram bot
  - Each message is a conversational Claude Code turn that remembers prior turns
  - Claude's replies are relayed to Telegram; tool calls are Approve/Deny gated
  - Conversation ids persist so a daemon restart resumes where you left off
  - A hard-deny override always blocks the dangerous set, even over allow rules
non_goals:
  - NOT a second permission/allowlist system parallel to Claude Code
  - NOT auto-running the dangerous set (it is denied outright)
  - NOT inbound networking (no open ports, no Tailscale) for this path
---

# Telegram Ops Lane

## Summary

A private phone lane that lets you **chat with real Claude Code** on the host
machine over Telegram — the full agent (files, bash, git, MCP tools, subagents),
not a subset. Each message is a conversational turn under a working root you
configure; Claude's replies come back to you and tool calls are gated with an
Approve/Deny tap. Permission policy is Claude Code's own; the lane adds only an
identity lock, a relay, and a hard-deny override for the dangerous set.

## Behavior

The daemon long-polls one bot (outbound only) and obeys only allowlisted user
IDs. Every message runs `claude -p --resume <session> --output-format json`
under the configured root, so the conversation remembers prior turns; the reply
text is relayed to Telegram. Tool calls resolve against your loaded Claude Code
settings: `deny` blocks, `allow` runs silently, and anything else is surfaced to
your phone via the `--permission-prompt-tool` (a small MCP broker that records
the pending action to a file spool and blocks for your tap; timeout parks it as
a deny). Conversation ids are persisted, so restarting the daemon resumes the
same conversation. `/ls` lists folders under the root, `/new` starts fresh.

## Capability vs. lockdown

By default the phone loads your **full desktop config** (`setting_sources=all`:
MCP servers, custom commands, agents, allow rules) for parity, with a strict
**deny-only override** layered on top via `--settings`. Because deny beats
allow, the dangerous set (`gcloud … delete`, billing, key creation, `rm -rf`,
secret reads) is always blocked even though everything you already allow on the
desktop runs without a prompt. Set `RISTRETTO_OPS_SETTING_SOURCES=project` to
exclude your desktop rules and make sensitive actions ask again;
`RISTRETTO_OPS_STRICT_MCP=1` restricts to only the approval server.

## Out of scope

- NOT a second allowlist: policy stays in Claude Code's settings + the deny file.
- NOT auto-running the dangerous set: it is denied outright.
- NOT inbound networking.

## Implementation notes

Package `ristretto.ops_lane`. Config and secrets live in the lane's OWN env
file, `~/.config/ristretto/ops.env` (isolated from Hermes's shared
`~/.hermes/.env` so the gateway's Telegram platform can't pick up the bot
token): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, and `RISTRETTO_OPS_ROOT`.
Conversation ids persist to `~/.hermes/ops-sessions.json`. Run with
`ristretto ops-daemon` (`--check` validates config). Verified end-to-end against
Claude Code 2.1.x. Relaying outcome summaries to team Slack via `hermes send`
is planned but not yet wired.
