---
id: zam-assistant
title: Zam Assistant Loop
status: in-progress  # proposed | in-progress | implemented | deprecated
created_at: 2026-09-27
last_modified: 2026-09-27
owner: project
depends_on: [fleet-view, approval-loop, autonomous-coding, custom-model-flows]
acceptance_criteria:
  - One configured provider runs the loop - `instance.assistant_provider`,
    falling back to `claude` when the key is unset
  - The provider is read from configuration, never hardcoded, so the switch to
    a local provider is a configuration change and not a code change
  - A named conversation continues across turns, so a surface can keep a
    thread without tracking a session id itself
  - The loop answers from its tools rather than from the model's guess - the
    fleet, and the vault, are read through tools
  - `propose_merge` records a pending approval naming one fixed PR number and
    never merges
  - `launch_run` refuses without an explicit project, because an issue key
    alone is ambiguous across repositories
  - A turn that fails returns a message the surface can render, and never
    raises, on every surface
  - Every prompt names tool output as data and never as instructions
  - A wedged turn ends on a timeout rather than hanging a chat surface
  - Every surface is granted the same tools - there is no per-surface subset,
    so a tool added to the table is reachable from all four at once
non_goals:
  - NOT merging or deploying on its own say-so - both route through
    `approval-loop`
  - NOT a coding tier - it dispatches them, it is not one, and it is one
    provider rather than a per-stage pipeline
  - NOT a second definition of a live run - the fleet is read through
    `runs.py`, per `fleet-view`
  - NOT writing to the vault - the reader is wired, the writer is Phase 2 and
    `cuzam/assistant/vault.py` is read-only by design
  - NOT a second assistant - the face, the dashboard, the CLI and Slack reach
    this loop, they do not each carry their own
test_plan:
  - "Provider resolution: with `instance.assistant_provider` unset, assert the
    loop resolves `claude`; set it to `local-brain` and assert it resolves
    that. Prove it bites by hardcoding the provider and watching the second
    assertion fail."
  - "Continuity: run two turns against one `--conversation` key and assert the
    second command carries `--resume` with the id the first stored. Prove it
    bites by dropping the store write and watching the second turn open a new
    session."
  - "Gate: call `propose_merge` against a fixture with an open PR and assert a
    pending approval exists naming that PR number, and that no merge command
    ran."
  - "Ambiguity: call `launch_run` with an issue key and no project and assert
    it refuses without launching."
  - "Never raises: drive a turn with the provider binary missing from PATH and
    assert a Turn with ok False and a renderable message, not an exception."
---

# Zam Assistant Loop

## Summary

The conversational half of Zam: one model, its own tools, and a conversation
that continues. It is the thing the product is named after, and until it
existed the assistant was a proxy that shelled Hermes and returned the answer.
It turns the morning brief from a daily monologue into something you can
answer — ask what is running, ask it to start an issue, ask it to queue a PR
for your approval — from the CLI, the dashboard, the desktop face, or Slack.

## Behavior

One turn is one question and one answer. The loop resolves a single provider
from `instance.assistant_provider` and drives it as `claude -p` over an MCP
tool server that this repository ships, which is the approval broker's
mechanism — so it needs no API key and no new dependency. When the key is
unset the provider is `claude`: the loop is cloud by default, and
`local-brain`'s boundaries describe the Hermes orchestrator path rather than
this one.

Continuity has two shapes, because the surfaces differ. A caller that owns a
durable name — the CLI with `--conversation`, the Slack plugin with the
channel id — hands that name over and the loop maps it to a session it keeps
on disk, so the thread survives across processes. A caller that owns a client
session — the dashboard, the desktop face — hands back the session id from the
previous turn. Both continue a conversation; they do not currently continue
*the same* conversation, so a thread started on the face is not the thread
Slack is holding.

The tools are the boundary, and they are the same boundary everywhere. The
loop allowlists the whole table on every call, so there is no read-only slice
for a surface that might want one: a tool added to the table is reachable
from the CLI, the dashboard, the face and Slack the moment it is added. What
bounds the risk is who can reach a surface at all — `slack-gateway` allows one
user — and what each tool is permitted to do, not which surface asked.

Reading the fleet and reading the vault are answered directly. Starting a
coding run also executes directly, guarded by the launcher's own checks — a
valid issue key, a committed verify gate, a refusal when the fleet is already
busy — because a run produces a pull request that a human reviews before
anything merges. Merging does not execute: it resolves
the issue to one open PR, fixes that PR number, and records a pending approval
for the user to confirm, so what gets merged cannot change between the
proposal and the approval. Deploy is not reachable at all yet.

A turn never raises. A missing configuration, an unreachable provider, a
non-zero exit or an empty answer all come back as a turn the surface can
render, because a chat window that throws is a chat window that is gone. A
turn that wedges ends on a timeout for the same reason.

## Out of scope

- **NOT merging or deploying on its own say-so.** These are the two actions
  the approval store exists for. `propose_merge` is deliberately named for
  what it does; the tool description says it does not merge, so the model is
  not left to infer it.
- **NOT a coding tier.** A tier is a pipeline of stages that produces a PR,
  with a reviewer that is never the builder. This is a conversation: one
  model, one provider, back and forth. It dispatches tiers; it does not run
  on one.
- **NOT a second definition of a live run.** `fleet_status` reads `runs.py`,
  the module `fleet-view` pins to `scripts/live-runs.sh` by contract test.
  A tool that computed liveness itself would be the third answer that contract
  exists to prevent.
- **NOT writing to the vault.** The reader is wired and reaches every stage;
  `cuzam/assistant/vault.py` is read-only by design and says so. The writer is
  Phase 2 of the roadmap and is where the "better every time" promise actually
  lives.
- **NOT a second assistant.** Four surfaces reach this one loop. `fleet-view`
  already carries the matching non-goal from the dashboard's side.

## Open questions

- [ ] **It has never been dogfooded.** Every claim above is about what the
      code does, not about whether the assistant is any good. Whether the
      loop holds a useful conversation, calls the right tool, and gets the
      arguments right is unmeasured. That is a different problem from unbuilt
      and it is the reason this is `in-progress` rather than `implemented`.
- [ ] **Should the four surfaces share one thread?** Today they do not. One
      continuous conversation across the face, the dashboard and Slack is what
      the roadmap's Phase 1 asks for, and it needs a durable name for the
      client-session surfaces before it is possible.
- [ ] **When does the default become local?** The roadmap's sequencing is ship
      on Claude, get the loop correct, then swap and find out what breaks.
      The trigger is unstated. See `local-brain`.
- [ ] **The third intent is absent.** Phase 1 asks for "describe new work" to
      scaffold a Linear issue and then dispatch. No tool does this; there is
      no Linear tool in the table at all.
- [ ] **Should a surface be able to hold a narrower set of tools?** Slack can
      start a coding run today, because every surface gets every tool. That is
      defensible while the gateway is one allowlisted user and a run ends at a
      reviewable PR, and it stops being defensible the moment either changes.
      The mechanism does not exist, so the question is currently answered by
      accident rather than on purpose.
- [ ] **Is `launch_run` on the right side of the gate?** It is allowlisted and
      it spends money and starts a process. The argument for executing it
      directly — dev work, ends at a reviewable PR — is written down and looks
      sound, but it is the one mutating capability that does not pass through
      `approval-loop`, and it deserves a decision rather than an inheritance.

## Implementation notes (optional)

`cuzam/assistant/loop.py` is the loop; `cuzam/assistant/tools.py` is the tool
server and the single place the capabilities are declared;
`cuzam/assistant/vault.py` is the read-only vault access behind two of them.

Surfaces: `cuzam chat` (`cuzam/cli.py`), the dashboard's `/chat`
(`cuzam/dash/app.py`), the desktop face which posts to that same endpoint
(`zam/Zam.swift`), and the `zam-chat` Hermes plugin for Slack, which passes
the channel id as the conversation key.

Two contract facts inherited from `broker.py` and kept in the tool server: the
MCP server must advertise its tools capability explicitly, and every reply
must be exactly one `TextContent` whose text is JSON — Claude Code rejects
FastMCP's `structuredContent`.
