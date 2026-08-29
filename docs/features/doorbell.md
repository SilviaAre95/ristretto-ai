---
id: doorbell
title: Doorbell
status: implemented  # proposed | in-progress | implemented | deprecated
created_at: 2026-08-30
last_modified: 2026-08-30
owner: project
depends_on: [event-spine, fleet-view]
acceptance_criteria:
  - Pipeline milestones arrive in Slack with a link into the fleet view
  - Progress events never notify
  - Nothing is announced twice
  - An undelivered milestone is never skipped
non_goals:
  - NOT notifying on every event
  - NOT running as a daemon
  - NOT retrying a failed send into a loop
---

# Doorbell

## Summary

Pipeline milestones arrive in Slack, each carrying a link into the fleet view.
Slack is the doorbell; the dashboard is the room.

## Why

A dashboard you have to remember to open is a dashboard you stop opening —
which is how the previous attempt died. The fix is not a better dashboard but
a reason to go to it, delivered somewhere already read.

## Behavior

Only outcomes and trouble ring: `run.started`, `run.ended`, `stage.failed`,
`verify.red`, `grader.failed`, `pr.opened`, `awaiting.approval`,
`preflight.failed`, `control.stop`. Stage starts and passes stay in the log.
A tier run emits six of each, and a channel that pings twelve times per task
is a channel nobody reads — so notifying on progress would cost more than
sending nothing.

Each message is one line a person can act on plus a link to the rest. Failure
detail is truncated: a build log belongs on the task page the link points at,
not in the channel. A pull request links to the pull request; a preflight
failure links nowhere, because it is not a run and `/task/<id>` would be dead.

A cursor in `${RISTRETTO_STATE_HOME:-~/.ristretto}/doorbell.cursor` records
the last delivered event. A failed send stops the pass without advancing it,
so an undelivered milestone is announced late rather than lost — the one
failure a notifier must not have.

## Scheduling

A cron every two minutes, not a daemon. A missed tick delivers late; a
crashed daemon delivers never, and nobody notices a silent notifier. Because
the cursor makes catching up free, lateness is the only cost of the simpler
mechanism.

## Out of scope

- NOT notifying on every event.
- NOT a daemon.
- NOT retrying a failed send into a loop — it reports and waits for the next tick.

## Open questions

- Should milestones thread under the task rather than posting flat?
- The morning brief and the doorbell both post to Slack; they may want merging.
