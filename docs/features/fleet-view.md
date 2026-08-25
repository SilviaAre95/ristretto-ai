---
id: fleet-view
title: Fleet View
status: in-progress  # proposed | in-progress | implemented | deprecated
created_at: 2026-08-25
last_modified: 2026-08-25
owner: project
depends_on: [event-spine]
acceptance_criteria:
  - Every run across every project is visible from a phone on the tailnet
  - A run that has gone quiet is shown as stalled, not as healthy
  - The view never claims a signal it did not receive
  - No route mutates anything in this phase
non_goals:
  - NOT binding to a public interface
  - NOT stopping, unblocking, or launching work in V1
  - NOT implying a heartbeat Hermes does not expose
---

# Fleet View

## Summary

`ristretto dash` serves a read-only view of every run across every project,
joining Hermes' task board to Ristretto's pipeline event log on task id. It
binds to this machine's Tailscale address, so a phone or iPad on the tailnet
can reach it and nothing else can.

## Behavior

Cards group by project, projects with live work first, each showing the issue,
current stage, elapsed time, and how long since the last signal. Colour and a
pill encode health so the state reads at a glance: running, stalled, blocked,
failed, done. A task page adds the full pipeline timeline and Hermes' own run
history, including the error text that explains a crash.

Server-sent events push a compact digest every few seconds and only when
something changed, so a quiet fleet costs a query and sends nothing.

### Liveness, honestly

The design called for a heartbeat-age rule, but Hermes exposes no
`last_heartbeat_at` through its CLI, and reaching into `kanban.db` would break
the boundary the event spine deliberately keeps. Liveness is therefore derived
from the newest signal Ristretto actually has — a recorded pipeline event, or
failing that the run's start — and every card states which one it used. A run
that is active with no signal for fifteen minutes is shown as stalled.

A finished task with no recorded completion time reports its duration as
unknown rather than counting from its start, which would grow forever and read
as though the work were still in flight.

### Binding

The address is the tailnet one when Tailscale is up and loopback otherwise.
`0.0.0.0`, `::`, and `*` are refused outright rather than merely discouraged:
the gap between "reachable from my iPad" and "reachable from the café wifi" is
one absent-minded flag.

## Out of scope

- NOT public ingress: there is no auth layer, because there is no exposure.
- NOT mutating: this phase has no POST, PUT, PATCH, or DELETE route at all,
  which a test pins. Stop, unblock, and launch arrive with the privilege split
  that should accompany them.
- NOT implying a heartbeat: see above.

## Open questions

- Retention: the fleet lists every task ever, including archived ones.
- Should the task page show the stage artifacts, or only the events?

## Implementation notes (optional)

The dashboard dependencies are the optional `[dash]` extra; the CLI and the
loop work without them, and the route tests skip when they are absent.
