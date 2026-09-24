---
name: durable-dev
description: Use when the user asks for dev work on a Linear issue ("do PROJ-71", "fix PROJ-42", "work on <issue>", "queue <issue>") — start it with `cuzam launch`, which claims a board task and spawns the flow as a detached process. Never run the loop inline; never create deploy tasks.
version: 2.0.0
author: Silvia Arellano
license: MIT
metadata:
  hermes:
    tags: [kanban, loop-dev, producer, durable, linear]
    related_skills: [issue-closeout]
---

# Durable Dev (producer)

Dev work must survive crashes and restarts, so it is started as a detached process — never executed in this conversation. You call `cuzam launch` and return; it does the rest.

`cuzam launch` claims the board task, cuts the worktree at `origin/<base>`, and spawns the flow in its own session. **No worker agent is involved and there is nothing for the dispatcher to pick up** — the task is created deliberately unassigned, which is what keeps an agent away from it. You are the producer and nothing else.

This replaced a `hermes kanban create --assignee zam-worker` on 2026-09-24. A dispatched worker meant a language model was the thing running a script and waiting for it; on 2026-09-10 one abandoned a run and killed two more across four attempts on a single issue, reading a silent stage as a hang. The `loop-runner` skill it used no longer exists.

## Steps

1. **Resolve the issue.** Get the Linear issue for the key and its project name. Resolve the local repository only through the user-owned Cuzam configuration: `cuzam repo resolve "<exact Linear project name>"`. If the project is not configured, tell the user which mapping is missing and stop instead of guessing a path. Use the issue's git branch name.

2. **Resolve the flow.** Run `cuzam flow list` to get the validated names. Selection rules:
   - Explicit `using <flow>` or an explicit stage request (for example "plan with Claude, build locally, review with Codex") → choose the matching configured flow and validate it with `cuzam flow show <name>`.
   - A request for more scrutiny ("review it properly", "be careful with this") → `flow: full`. A request for less on a small change ("quick one", "trivial") → `flow: short`, which has no review stage.
   - **There is no local coding flow.** "locally" used to select `tier3`; the tiers were retired on 2026-09-23 because local models do not write production code here. If the user asks for a local run, say so rather than silently picking a Claude flow.
   - No flow request → `flow: classic`, preserving the existing `/loop-dev` behavior.

   For `classic` only, pass `--model sonnet` by default; **omit `--model` entirely** for auth, payments, security, sensitive data, or requests containing "carefully", so the run gets the strongest model. `--model local` was removed with the tiers and is accepted-and-dropped rather than rejected, so an old request still runs on the Claude default instead of failing. A non-classic flow takes its models from its stages and **refuses** `--model` — do not pass one.

3. **Start it.** One command. It does the preflight, pins the branch to `origin/<base>`, creates the task and spawns the flow:
   ```bash
   cuzam launch "<exact Linear project name>" <KEY> --flow <validated flow> --model sonnet --actor zam
   ```
   It prints `task: t_...` on success. On failure it prints `not launched: <reason>` and exits non-zero — **report that reason verbatim and stop.** Never retry with different arguments, never fall back to `hermes kanban create`, and never run the loop yourself. Common refusals are all deliberate: the repo cannot run a loop yet, a run is already active, the branch cannot be cut cleanly from `origin/<base>`, or the flow does not accept a model tier.

   You no longer check `.cc-dev.yaml` or pre-create the branch. `launch` does both, and doing them here as well meant two answers that could disagree.

4. **Subscribe alerts.** With the task id `launch` printed:
   ```bash
   alert_channel="$(cuzam instance get slack_alerts_channel)" || exit 1
   hermes kanban notify-subscribe <task_id> --platform slack --chat-id "$alert_channel"
   ```

5. **Reply with one line:** `On it. <KEY> started.` — nothing else. Do not narrate; the doorbell posts milestones and the flow reports its own outcome.

## Guardrails

- NEVER run the loop inline in this conversation. Handing it to `cuzam launch`
  is the point: deterministic work does not belong inside an agent turn, and
  that includes yours.
- NEVER absorb a started run. When the user pushes ("kick it off now", "why is
  it not moving", "start it"), run `cuzam runs <KEY>` and report what it says —
  it reads the process table, so it distinguishes a live run from a dead one.
  **Nothing is waiting on a dispatcher poll:** `launch` spawns the flow itself
  and the task is unassigned, so "it will be picked up shortly" is never the
  answer. If the run is dead, `cuzam relaunch <KEY>` is the deliberate way back
  and it starts again from `plan`. Implementing the task in this conversation —
  via the loop, ad-hoc edits, or subagents — is forbidden however it is asked.
- `hermes kanban remove` is for explicit user-requested cancellation only,
  never a step toward doing the work inline. If the user truly wants inline
  work, they must first ask to cancel the task — then confirm before
  proceeding inline, and the deploy guardrail still applies.
- NEVER create a deploy task. Deploys stay inline with the user present until the phone-approval gate is proven on an unattended run. If asked to queue a deploy, explain that and offer the supervised inline flow.
- Do not pass an idempotency key. `launch` derives one from the issue, the flow and the day, so a repeated ask today is one task and a genuine retry tomorrow is allowed. Passing your own would defeat both halves.
- Move the Linear issue to In Progress after starting the run.
