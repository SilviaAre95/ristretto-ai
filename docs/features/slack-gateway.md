---
id: slack-gateway
title: Slack Gateway
status: implemented  # proposed | in-progress | implemented | deprecated
created_at: 2026-07-05
last_modified: 2026-07-05
owner: project
depends_on: []
acceptance_criteria:
  - Connects via Socket Mode (no public URL)
  - Only allowlisted user (`SLACK_ALLOWED_USERS`) is answered
  - Responds to DMs and to @mentions in invited channels
non_goals:
  - NOT public/multi-user
  - NOT other chat platforms in V0
  - NOT unauthenticated access
---

# Slack Gateway

## Summary

Ris talks to one configured user in Slack over Socket Mode, restricted by member ID. No public endpoint is exposed, and non-allowlisted users cannot invoke or receive responses from the assistant.

## Behavior

Ris connects to Slack over Socket Mode, so no public URL or inbound webhook is required. For each DM or invited-channel mention, the gateway checks the sender against `SLACK_ALLOWED_USERS`. Non-allowlisted events are ignored; the configured user receives a response in the same DM or thread.

## Out of scope

- NOT public/multi-user: V0 serves one explicitly allowlisted user. Multi-user support would require per-user authorization, scoping, and audit trails.
- NOT other chat platforms in V0: only Slack is wired up. Telegram, email, or other channels are not implemented and are not on the V0 roadmap.
- NOT unauthenticated access: every inbound event is checked against the allowlist before any processing occurs; there is no anonymous or guest mode.

## Open questions

## Implementation notes (optional)

The Slack app runs through Hermes Agent's Socket Mode gateway. `SLACK_ALLOWED_USERS` is set in `~/.hermes/.env` and is never committed.
