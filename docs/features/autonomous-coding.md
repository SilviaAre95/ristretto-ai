---
id: autonomous-coding
title: Autonomous Coding
status: in-progress  # proposed | in-progress | implemented | deprecated
created_at: 2026-07-05
last_modified: 2026-09-24
owner: project
depends_on: [approval-loop, filesystem-scoping]
acceptance_criteria:
  - Works on a branch
  - Opens a PR
  - Never pushes to main unattended
  - Every risky step passes the approval loop
  - Notifies the user in Slack with the real PR URL
  - After merge, hands off to deployment tracking when configured
  - Refuses to start when the run's filesystem scope cannot be applied
non_goals:
  - NOT auto-merging
  - NOT acting on employer systems without confirmed authorization
  - NOT running before the approval loop is proven
  - NOT executed inside any agent turn — the launcher spawns the flow directly
  - NOT reading outside its declared filesystem scope — see
    `filesystem-scoping`
---

# Autonomous Coding

## Summary

Zam delegates coding work to a selected, supervised flow that works on a branch and opens a PR. `classic` uses Claude Code; configurable flows assign Claude Code, a local model, or Codex independently by stage.

## Behavior

The selected flow never pushes to the base branch unattended. Risky steps pass through the approval loop. Every flow is started the same way: `launch` claims the board task, cuts the worktree at `origin/<base>`, and spawns the flow as a detached process. No agent starts, supervises, or reports a run. `classic` resumes a cloud session per worktree after a crash; multi-stage flows exchange explicit artifacts between fresh isolated processes. When ready, Zam posts the exact PR URL for user review and merge.

## Out of scope

- NOT auto-merging: opening the PR is as far as this feature goes — merging is a separate, human decision.
- NOT acting on employer systems without confirmed authorization: those repositories remain out of scope by default.
- NOT running before the approval loop is proven: this feature depends on the approval loop being proven first and does not operate until then.
- NOT executed inside an agent turn: deterministic work does not belong in one. On 2026-09-10 a worker agent abandoned one run and killed two more across four attempts on a single issue, reading a silent stage as a hang, twice while quoting back the instruction telling it not to. Hermes' supervision was never the problem — it leases a claim, watches a pid, and expects a heartbeat, all deterministic. So the assistant turns a request into a launch and stops there. It may report, promote, or (on explicit request) cancel a run; it never runs one, and it never absorbs one into its own turn.

## Open questions
