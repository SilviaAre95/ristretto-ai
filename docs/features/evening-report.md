---
id: evening-report
title: Evening Report
status: proposed  # proposed | in-progress | implemented | deprecated
created_at: 2026-07-05
last_modified: 2026-07-05
owner: project
depends_on: [linear-integration, slack-gateway]
acceptance_criteria:
  - Fires at 18:00
  - Reports shipped work, PRs, and blockers to the configured channel
  - Updates Linear issue states to match the day's events
non_goals:
  - NOT changing issue states without a real event
  - NOT duplicating the morning brief
---

# Evening Report

## Summary

A 6pm cron will summarize shipped work, PRs, and blockers in the configured channel and keep Linear states aligned with real events.

## Behavior

At 18:00, Ris will post a summary to the configured Slack channel. Linear states may change only when backed by a real event; the report does not speculate or repeat the morning brief.

## Out of scope

- NOT changing issue states without a real event: Linear issue states are only updated when a real event during the day justifies the change — no speculative or automatic state changes.
- NOT duplicating the morning brief: the evening report covers the day's shipped work, PRs, and blockers — it is not a re-post of the morning brief's content.

## Open questions

- [ ] What counts as a "real event" that justifies a Linear issue state change (e.g., a merged PR, a closed task) is not specified.

## Implementation notes (optional)
