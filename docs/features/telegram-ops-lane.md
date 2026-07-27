---
id: telegram-ops-lane
title: Telegram Ops Lane
status: in-progress
created_at: 2026-07-27
last_modified: 2026-07-27
owner: project
depends_on: []
acceptance_criteria:
  - A dedicated daemon owns one identity-locked Telegram bot
  - You name the repo before any task runs; the daemon never guesses
  - Claude Code's own settings decide allow/ask/deny; only ask reaches Telegram
  - Every gated action is echoed, tapped, and audited; timeout parks as deny
non_goals:
  - NOT a second permission/allowlist system parallel to Claude Code
  - NOT auto-running anything; ask always prompts
  - NOT inbound networking (no open ports, no Tailscale) for this path
---

# Telegram Ops Lane

## Summary

A private phone lane that drives real headless Claude Code on the host machine.
Permission policy is Claude Code's own (`.claude/settings.json` per repo,
`~/.claude/settings.json` user-level). The daemon adds only an identity lock and
a faithful relay of `ask` prompts to Telegram as Approve/Deny.

## Behavior

The daemon long-polls one bot (outbound only), obeys only allowlisted user IDs,
pins a session to a repo you name, and launches
`claude -p --permission-prompt-tool mcp__approve__ask` there. Settings `deny`
blocks before the tool is called; `allow` runs silently; only `ask`/unmatched
calls are surfaced to your phone. Timeout parks the action as a deny.

## Out of scope

- NOT a second allowlist: policy stays in Claude Code's settings.
- NOT auto-run: silence never approves.
- NOT inbound networking.

## Implementation notes

Package `ristretto.ops_lane`. Secrets (`TELEGRAM_BOT_TOKEN`,
`TELEGRAM_ALLOWED_USERS`) live only in `~/.hermes/.env`. Outcome summaries post
to team Slack via `hermes send`.
