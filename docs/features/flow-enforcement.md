---
id: flow-enforcement
title: Flow Enforcement
status: implemented  # proposed | in-progress | implemented | deprecated
created_at: 2026-08-27
last_modified: 2026-08-27
owner: project
depends_on: [autonomous-coding, custom-model-flows]
acceptance_criteria:
  - A loop task cannot be completed unless its loop ran
  - The evidence is written by the loop itself, not by best-effort telemetry
  - Anything the guard cannot determine fails open
non_goals:
  - NOT gating tasks that are not loop tasks
  - NOT relying on the event log, which is deliberately best effort
  - NOT preventing a worker from editing files, only from calling it done
---

# Flow Enforcement

## Summary

A worker may not mark a loop task done unless the loop actually ran. A
`pre_tool_call` shell hook on `kanban_complete` checks for the run marker that
`run-loop.sh` writes, and refuses the completion when it is absent.

## Why

The loop-runner skill already says to run `run-loop.sh` and explicitly not to
drive the coding tools directly. A worker ignored it: it edited files with its
own terminal tool, called `kanban_complete`, and opened a pull request that
deleted a block of security headers — HSTS, `X-Frame-Options`, `nosniff`,
Referrer-Policy, Permissions-Policy and DNS-prefetch — while claiming to be a
config rename. No plan, review, repair, or verify stage ever ran. Hermes
recorded the task as `done`.

Every guard built before this one sits *inside* a flow: stage-output checks,
the pr-stage post-condition, the deterministic verify gate. None of them
applied, because the flow was never entered. Instructions in a skill are a
request; this is the enforcement.

## Behavior

`run-loop.sh` writes `<worktree>/.ristretto/runs/<task-id>/loop.json` before it
does anything else, and the multi-stage runner writes `flow.json` beside it.
The marker is written directly rather than through the event emitter, because
telemetry is best effort by design and must never be load-bearing: an
unwritable event store would otherwise look exactly like a loop that never ran.

The hook gates only tasks whose body carries the loop contract (`issue:` and
`repo:`). Anything else on the board is somebody else's work. When it does
refuse, the message names the flow that was skipped, gives the exact command to
run, and tells the worker to revert its own edits first — output that has had no
plan, no review and no verification must not reach a pull request.

Hooks are per profile, and the worker runs under `ris-worker`. Declaring the
guard only in the top-level config would leave the one process it exists to
gate entirely ungated, so the installer sets it on the worker profile, with
`hooks_auto_accept` because a detached worker has no TTY to consent at.

## Out of scope

- NOT gating non-loop tasks.
- NOT relying on the event log.
- NOT stopping a worker from editing files — only from calling that done.

## Open questions

- Crash recovery skips the loop when a PR already exists. The marker survives
  in the worktree, so this holds today, but a recreated worktree would refuse.
- Should a blocked completion also emit an event, so the fleet view shows it?
