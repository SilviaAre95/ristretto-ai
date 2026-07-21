---
id: morning-brief
title: Morning Brief
status: implemented  # proposed | in-progress | implemented | deprecated
created_at: 2026-07-05
last_modified: 2026-07-17
owner: project
depends_on: [linear-integration, slack-gateway]
acceptance_criteria:
  - Fires at 08:00 daily
  - Groups by project and leads with priority
  - Ends by asking what to work on
  - Delivered to the configured Slack home channel
  - Suppresses delivery when the configured board snapshot is unchanged
non_goals:
  - NOT acting on the board automatically
  - "NOT posting when nothing is new (uses `[SILENT]`)"
---

# Morning Brief

## Summary

An 8am cron posts a prioritized, project-grouped board brief to the configured Slack home channel and prompts the user to choose a focus.

## Behavior

Every day at 08:00, a precheck snapshots the configured open board and compares it with the previous snapshot. It emits a compact delta plus Urgent, High, and In Progress issues, or exactly `NO_CHANGES`. Ris composes the brief and asks what the user wants to work on. `[SILENT]` suppresses unchanged delivery.

## Out of scope

- NOT acting on the board automatically: the brief is read-only reporting — Ris does not create, update, or close Linear issues as part of generating or sending it.
- NOT posting when nothing is new: rather than posting a noisy "nothing to report" message every day, the brief is skipped (marked `[SILENT]`) when there's no new signal.

## Open questions

None.

## Implementation notes (optional)

Scheduled via Hermes cron and delivered to `instance.slack_home_channel`. The precheck is deployed to `~/.hermes/scripts/`; it owns the single read-only Linear call so the composing model receives no tool schemas.

Live verification on 2026-07-17: an initial run delivered the brief; an immediate unchanged run returned `[SILENT]`, logged `skipping delivery`, and used 1,627 input tokens versus 14,771 before removing agent tool schemas.
