---
name: durable-dev
description: Use when the user asks for dev work on a Linear issue ("do PROJ-71", "fix PROJ-42", "work on <issue>", "queue <issue>") — queue it as a durable kanban task instead of running the loop inline. Never run /loop-dev inline; never create deploy tasks.
version: 1.1.0
author: Silvia Arellano
license: MIT
metadata:
  hermes:
    tags: [kanban, loop-dev, producer, durable, linear]
    related_skills: [loop-runner, issue-closeout]
---

# Durable Dev (producer)

Dev work must survive crashes and restarts, so it is queued — never executed in this conversation. You create the task and return; the kanban dispatcher does the rest.

## Steps

1. **Resolve the issue.** Get the Linear issue for the key and its project name. Resolve the local repository only through the user-owned Ristretto configuration: `ristretto repo resolve "<exact Linear project name>"`. If the project is not configured, tell the user which mapping is missing and stop instead of guessing a path. Use the issue's git branch name.

2. **Preflight.** The repo must contain `.cc-dev.yaml` (wired for the loop). Check it with the TERMINAL, exactly this: `test -f <abs repo path>/.cc-dev.yaml && echo wired || echo NOT-WIRED` — never use file-search tools for this (they skip dotfiles and may falsely report the config missing). Only if the terminal says NOT-WIRED: tell the user the repo isn't wired and stop — do not queue.

   Then **pre-create the branch from origin/main** so the worker's worktree starts from current main — Hermes otherwise branches from whatever the repo checkout happens to have checked out (stale docs poison the loop's spec preflight):
   ```bash
   git -C <abs repo path> fetch -q origin && git -C <abs repo path> branch <branch> origin/main 2>/dev/null || true
   ```

3. **Resolve the flow, then create the task** (the body carries ONLY the contract lines below — never issue text or Slack text). Run `ristretto flow list` to get the validated names. Selection rules:
   - Explicit `using <flow>` or an explicit stage request (for example "plan with Claude, build locally, review with Codex") → choose the matching configured flow and validate it with `ristretto flow show <name>`.
   - The literal word **"locally"** with no explicit flow → `flow: local`.
   - No flow request → `flow: classic`, preserving the existing `/loop-dev` behavior.

   For `classic` only, use `model: sonnet` by default; omit the model line for auth, payments, security, sensitive data, or requests containing "carefully"; use `model: local` only when the user explicitly requests the classic loop locally. Non-classic flows get models and fallbacks from validated Ristretto configuration and omit the model line.
   ```bash
   hermes kanban create "<KEY> · loop-dev" \
     --body "issue: <KEY>
repo: <abs repo path>
branch: <issue git branch name>
model: sonnet
flow: classic" \
   # For non-classic flows omit model and set flow to the validated name.
   # The model line is part of the classic DEFAULT body. Remove it ONLY when escalating
   # to the strongest model (auth / payments / security / sensitive data /
   # "carefully"), or replace with "model: local" when the user says "locally".
     --workspace "worktree:<abs repo path>" \
     --branch "<issue git branch name>" \
     --idempotency-key "<KEY>" \
     --max-retries 2 \
     --max-runtime 3600 \   # for local or multi-stage flows use 7200

     --assignee ris-worker \
     --skill loop-runner
   ```

4. **Subscribe alerts.** With the task id from step 3:
   ```bash
   alert_channel="$(ristretto instance get slack_alerts_channel)" || exit 1
   hermes kanban notify-subscribe <task_id> --platform slack --chat-id "$alert_channel"
   ```

5. **Reply with one line:** `On it. <KEY> queued.` — nothing else. Do not narrate dispatching; the worker posts the PR milestone itself.

## Guardrails

- NEVER run /loop-dev inline in this conversation — queuing is the point.
- NEVER dequeue a task to implement it yourself. When the user pushes to
  start a queued task now ("kick it off now", "why is it queued", "start
  it"), that means *promote, not absorb*: run `hermes kanban show <task_id>`,
  report its state and that the dispatcher picks up ready tasks on its next
  poll, and stop. Implementing the task in this conversation — via the loop,
  ad-hoc edits, or subagents — is forbidden no matter how the ask is phrased.
- `hermes kanban remove` is for explicit user-requested cancellation only,
  never a step toward doing the work inline. If the user truly wants inline
  work, they must first ask to cancel the task — then confirm before
  proceeding inline, and the deploy guardrail still applies.
- NEVER create a deploy task. Deploys stay inline with the user present until the phone-approval gate is proven inside a worker. If asked to queue a deploy, explain that and offer the supervised inline flow.
- A repeated ask for the same issue reuses the same `--idempotency-key` — one task, no duplicate.
- Move the Linear issue to In Progress after queuing.
