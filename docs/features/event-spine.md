---
id: event-spine
title: Event Spine
status: in-progress  # proposed | in-progress | implemented | deprecated
created_at: 2026-08-25
last_modified: 2026-08-25
owner: project
depends_on: [custom-model-flows, autonomous-coding]
acceptance_criteria:
  - Every stage boundary records an event with a reason, not just an exit code
  - Telemetry failure never fails the run it is describing
  - Event kinds are a closed vocabulary
  - A repository can be proven loop-capable before a task is dispatched
non_goals:
  - NOT writing into Hermes' kanban schema
  - NOT a dashboard or any UI in V1
  - NOT failing a build when the event store is unavailable
---

# Event Spine

## Summary

Ristretto records its own pipeline events — stages, graders, verify gates,
pull requests — to an append-only log it owns. Hermes' kanban tracks a task's
lifecycle (claimed, spawned, blocked) and has no concept of these, so a run
could fail three different ways and leave nothing behind explaining which.
`ristretto events` reads the log; `ristretto preflight` proves a repository
can run a loop before one is dispatched.

## Behavior

The multi-stage runner emits `run.started`, `stage.started`, then
`stage.passed` or `stage.failed` per stage, plus `verify.green` / `verify.red`
for the deterministic gate, `pr.opened` when a pull request URL is reported,
and `run.ended` with an outcome. `stage.failed` carries the reason the runner
already computed — "model reported failure", "pr stage committed nothing on
top of origin/main" — rather than a bare exit code. `run-loop.sh` emits the
same run-level events for the classic path, including the Claude-unavailable
fallback.

Emitting is best effort operationally and strict programmatically: an
unreachable or corrupt store is reported on stderr and swallowed, while an
event kind outside the closed vocabulary raises, because that is a mistake in
the caller. Shell call sites also append `|| true`.

The store is `${RISTRETTO_STATE_HOME:-~/.ristretto}/events.db`, WAL mode,
append-only, outside the repository and never committed.

### Preflight

Every task builds in a fresh worktree from the base ref, so the loop only ever
sees what is committed. A developer's own checkout accumulates installed
dependencies, generated clients, and hand-made config; none of it exists in
the worktree, and the resulting failures look like the model wrote broken code.

`ristretto preflight <project>` checks that `.cc-dev.yaml` and `.cc-verify` are
committed on the base ref — not merely present on disk. `--deep` adds the only
check that settles it: create a worktree at that ref, install dependencies, and
run the verify gate. `origin/<base>` is preferred over the local branch, which
can sit weeks behind.

## Out of scope

- NOT writing into Hermes' kanban schema: Ristretto does not version the Hermes
  engine, and writing into another project's private tables breaks on upgrade.
- NOT a UI in V1: the log is read with `ristretto events` and `sqlite3`.
- NOT failing a build on telemetry error: an unwritable store degrades to a gap
  in the timeline.

## Open questions

- Should `preflight` run automatically before dispatch, or stay explicit?
- Retention: the log grows without bound and has no `gc` path yet.

## Implementation notes (optional)

Reasons come from `stage_output_failure()` and `pr_stage_failure()` in
`ristretto/runner.py`, so the event payload and the operator-facing message
cannot drift apart.
