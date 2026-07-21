---
id: autonomous-coding
title: Autonomous Coding
status: in-progress  # proposed | in-progress | implemented | deprecated
created_at: 2026-07-05
last_modified: 2026-07-18
owner: project
depends_on: [approval-loop]
acceptance_criteria:
  - Works on a branch
  - Opens a PR
  - Never pushes to main unattended
  - Every risky step passes the approval loop
  - Notifies the user in Slack with the real PR URL
  - After merge, hands off to deployment tracking when configured
non_goals:
  - NOT auto-merging
  - NOT acting on employer systems without confirmed authorization
  - NOT running before the approval loop is proven
---

# Autonomous Coding

## Summary

Ris delegates coding work to a selected, supervised flow that works on a branch and opens a PR. `classic` uses Claude Code; configurable flows assign Claude Code, a local model, or Codex independently by stage.

## Behavior

The selected flow never pushes to the base branch unattended. Risky steps pass through the approval loop. `classic` resumes a cloud session per worktree after worker crashes; multi-stage flows exchange explicit artifacts between fresh isolated processes. When ready, Ris posts the exact PR URL for user review and merge.

## Out of scope

- NOT auto-merging: opening the PR is as far as this feature goes — merging is a separate, human decision.
- NOT acting on employer systems without confirmed authorization: those repositories remain out of scope by default.
- NOT running before the approval loop is proven: this feature depends on the approval loop being proven first and does not operate until then.

## Open questions
