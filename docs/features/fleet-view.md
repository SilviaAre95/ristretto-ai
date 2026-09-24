---
id: fleet-view
title: Fleet View
status: in-progress  # proposed | in-progress | implemented | deprecated
created_at: 2026-08-25
last_modified: 2026-09-24
owner: project
depends_on: [event-spine]
acceptance_criteria:
  - Every run across every project is visible from a phone on the tailnet
  - A classic run is as visible as a staged one
  - A run that has gone quiet is shown as stalled, not as healthy
  - A run the board calls running with no process behind it is shown as dead
  - Nothing is called dead when the process table could not be read
  - Every locator needed to reach a run is shown - worktree, branch, log,
    runner pid, and for classic the Claude child pid
  - The same facts are available without a browser, from a command
  - Every surface renders one module and computes nothing of its own
  - The view never claims a signal it did not receive
  - Stopping and unblocking are possible from a phone
  - A stop that could not find the run's process says so, never reports success
  - A mutating request that did not come from this page is refused
  - Every control action is recorded in the timeline
  - The dashboard reaches the assistant through its own loop, not a second agent
non_goals:
  - NOT binding to a public interface
  - NOT a second assistant with its own tools or memory
  - NOT implying a heartbeat Hermes does not expose
  - NOT acting on a dead run - showing the truth never touches the board
  - NOT a second definition of what a live run is
---

# Fleet View

## Summary

`cuzam dash` serves a read-only view of every run across every project,
joining Hermes' task board to Cuzam's pipeline event log on task id. It
binds to this machine's Tailscale address, so a phone or iPad on the tailnet
can reach it and nothing else can. `cuzam runs` prints the same facts to a
terminal, so a worktree can be `cd`'d into and a log tailed without copying
paths out of a browser.

Both are renderers. What a run *is* — alive or dead, which shape, where its
worktree, branch and log are, which pids — is answered in one place,
`cuzam/runs.py`, which knows nothing about web frameworks, requests,
templates or sessions.

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
from the newest signal Cuzam actually has — a recorded pipeline event, or
failing that the run's start — and every card states which one it used. A run
that is active with no signal for fifteen minutes is shown as stalled.

A finished task with no recorded completion time reports its duration as
unknown rather than counting from its start, which would grow forever and read
as though the work were still in flight.

#### Dead, which is not stalled

`stalled` is a guess from silence; `dead` is a fact from the process table. A
run the board still calls `running` with no process behind it is shown as
dead, immediately, rather than reading healthy for fifteen minutes and then
reading as a guess.

`dead` is claimed only on evidence. When the process table cannot be read at
all — `ps` timing out under load is the realistic case — an absent answer is
not the answer "no": every surface says so and falls back to the signal-age
guess, because the alternative is painting a working fleet red and inviting
the operator to relaunch all of it.

**Nothing is done about it.** The board is not reclaimed, the card is not
moved, no process is signalled. On 2026-09-10 a surface that could not tell
alive from dead restarted a healthy run; a surface that can tell must still
not be the thing that acts.

Liveness keys on process shape, not on the flow's name: a `run-loop.sh` and a
`cuzam.runner` are two shapes covering three flows, so `classic` is visible and
a fourth flow cannot fall outside it silently. Both shapes are detached by the
launcher, so the distinction is which program is executing, never how it was
started. `scripts/live-runs.sh` stays a standalone bash implementation on
purpose — `install-runtime.sh` consults it while rebuilding
the Python environment, and a guard that imports the package to decide whether
it may replace the package is the circularity it exists to prevent. A contract
test pins the two against each other and names all three flows.

#### Locators come from truth

The worktree and branch are read from the board, which recorded them when the
run was created; the flow from the live process's own argv, or failing that
from what `launch` wrote into the task body; the runner pid from one `ps`
snapshot; the Claude child pid from the record `reap.sh` already maintains,
verified by pid, start time and command before it is shown. A log path is
shown only when the file exists, and inventing the path it would have had is
the kind of derivation this rule exists to forbid. A classic run now has one:
the launcher opens `flow.out` before spawning the loop, so the harness's own
output is captured for classic exactly as for a staged flow. Claude's own
output still goes to a temporary file and is written out when the run ends, so
`flow.out` is complete only once the loop exits — including when a stop ends it,
which the loop traps so that what Claude had said is not lost with it.

Streaming that output live was tried and reverted. Process substitution forks a
shell that does not exec, so it carries the loop's own argv and task id, and
both liveness implementations counted one run as two — with the fork outliving
the loop, so a stopped run read as live indefinitely. A run is one process, and
a test asserts that count rather than trusting it.

### Controls

A run can be stopped and a blocked task unblocked. Stop shells the existing
hardened kill switch, which reclaims the task, kills the run by its exact
spawn signature, verified-reaps the Claude Code grandchild, and re-checks for
the promote race. There is one signature per shape, and that count is
load-bearing: a shape with no signature is a stop that kills nothing, passes
its own verification — the task is blocked because it blocked it, and no pid
matches a signature that cannot match — and reports success while the run
carries on to `finish` and pushes. That has happened once already.

A count is not a guarantee, though, and the signatures cannot audit themselves:
"no pid matched" means either that the run is dead or that the pattern was
wrong, and the second reads exactly like success. So the verification also asks
`live-runs.sh`, the standalone answer to what a live run is — the one a contract
test pins against `cuzam/runs.py` and fails when a flow has no fixture. A live
process the kill signatures did not match therefore reports `NOT STOPPED` and
names itself, and a shape added to the launcher inherits the check instead of
waiting to be noticed. Its `NOT STOPPED` message and non-zero exit are surfaced
verbatim rather than translated into a cheerful failure. Both actions are
recorded as `control.stop` / `control.unblock` events, so a run that ends
early has a reason in its timeline instead of just stopping.

There is no login, so a mutating request must prove it came from this page.
Without that, any site visited while on the tailnet could post to the
dashboard from the browser and stop a running agent. Requests are accepted
only with `Sec-Fetch-Site: same-origin`, falling back to an `Origin` that
matches the host when the header is absent; `cross-site`, `same-site`,
`none`, a mismatched origin, and no headers at all are all refused.

**Starting work arrived with its own design.** Stopping a run costs a restart;
launching one spends tokens and writes code to a branch, so it was not added
by analogy to the other two — it has a validated form, an idempotency key, and
a preflight warning when the verify gate has not been proven.

### Asking Zam

`POST /chat` reaches the assistant's own loop — conversation state, its own
memory and its own tool boundary — and the dashboard is one surface onto it
rather than a separate agent.

The reason this is not a thin proxy is a security one and it still holds. An
agent with terminal, file, code execution and delegation, exposed unmodified on
a page with no login, is remote code execution over HTTP for anyone on the
tailnet: asked to run a shell command, it runs it and reports the output. The
assistant's tool boundary is explicit and small, which is the property that
makes the chat box safe. Widening it is a deliberate act, not a default.

The route is same-origin like the mutating ones. It changes nothing, but it
spends a model turn, and an endpoint anyone can drive is one anyone can drain.
The client returns the previous turn's session id, so the conversation
continues across requests instead of restarting each time.

### Why there is no separate dashboard user

The design called for the web process to run as an unprivileged `_risdash`.
It does not, because the split cannot work here and pretending otherwise
would be worse than not doing it: `zam-stop.sh` has to signal a worker owned
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
- NOT a second assistant: the dashboard holds no agent of its own. It renders a
  surface onto the assistant loop, so memory and tools are defined in one place
  and cannot drift between Slack and the browser.
- NOT implying a heartbeat: see above.

## Open questions

- Retention: the fleet lists every task ever, including archived ones.
- Should the task page show the stage artifacts, or only the events?

## Implementation notes (optional)

The dashboard dependencies are the optional `[dash]` extra; the CLI and the
loop work without them, and the route tests skip when they are absent.
