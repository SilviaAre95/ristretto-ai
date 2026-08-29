---
id: fleet-view
title: Fleet View
status: in-progress  # proposed | in-progress | implemented | deprecated
created_at: 2026-08-25
last_modified: 2026-08-30
owner: project
depends_on: [event-spine]
acceptance_criteria:
  - Every run across every project is visible from a phone on the tailnet
  - A run that has gone quiet is shown as stalled, not as healthy
  - The view never claims a signal it did not receive
  - Stopping and unblocking are possible from a phone
  - A mutating request that did not come from this page is refused
  - Every control action is recorded in the timeline
  - Ris answers questions about the fleet from the dashboard
non_goals:
  - NOT binding to a public interface
  - NOT launching work from the dashboard
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

### Controls

A run can be stopped and a blocked task unblocked. Stop shells the existing
hardened kill switch, which reclaims the task, kills the worker by its exact
spawn signature, verified-reaps the Claude Code grandchild, and re-checks for
the promote race; its `NOT STOPPED` message and non-zero exit are surfaced
verbatim rather than translated into a cheerful failure. Both actions are
recorded as `control.stop` / `control.unblock` events, so a run that ends
early has a reason in its timeline instead of just stopping.

There is no login, so a mutating request must prove it came from this page.
Without that, any site visited while on the tailnet could post to the
dashboard from the browser and stop a running agent. Requests are accepted
only with `Sec-Fetch-Site: same-origin`, falling back to an `Origin` that
matches the host when the header is absent; `cross-site`, `same-site`,
`none`, a mismatched origin, and no headers at all are all refused.

**Starting work is deliberately absent.** Stopping a run costs a restart;
launching one spends tokens and writes code to a branch, and it deserves its
own design rather than a third button added by analogy to the other two.

### Asking Ris

The same agent that answers on Slack answers here, narrowed twice.

Its tools are restricted to a minimal set. Ris normally has terminal, file,
code execution and delegation; exposed unmodified on a page with no login,
a chat box is remote code execution over HTTP for anyone on the tailnet —
asked to run a shell command, the unrestricted agent runs it and reports the
output. Verified: invoked with the restricted toolset it answers *"there's no
bash tool available in this environment"*. Widening this is a one-line change
and should be a deliberate one.

Context is injected rather than fetched. The dashboard already knows the
fleet, so it hands Ris a summary instead of granting the tools to go looking.
Fewer capabilities and better answers, and "why did XARI-33 stall" works
without naming a task id.

Replies are not streamed. `hermes -z` emits its whole answer at the end —
measured under a tty as well as a pipe, so it is the agent's behaviour and
not output buffering. Streaming would need `hermes serve`, a second daemon
running a JSON-RPC/WebSocket gateway; that earns itself when Ris is fully
capable here, not for read-only questions that land in under fifteen seconds.

### Why there is no separate dashboard user

The design called for the web process to run as an unprivileged `_risdash`.
It does not, because the split cannot work here and pretending otherwise
would be worse than not doing it: `ris-stop.sh` has to signal a worker owned
by the primary user, and one user cannot kill another's processes. Bridging
that needs a sudo rule letting the web user run a script as the owner, which
is itself an escalation path — more attack surface than the split removes.

The effort went into the boundary that is actually reachable instead: no
public bind, same-origin-only mutations, two verbs, validated ids, and an
audit trail.

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
