---
id: approval-loop
title: Approval Loop
status: in-progress  # proposed | in-progress | implemented | deprecated
created_at: 2026-07-05
last_modified: 2026-07-07
owner: project
depends_on: [slack-gateway]
acceptance_criteria:
  - "Dangerous actions render Approve/Deny (buttons + `!approve`/`!deny` fallback)"
  - Works from mobile
  - Unanswered prompts park the task (timeout)
non_goals:
  - NOT auto-approving destructive/spend/secret actions
  - NOT proceeding on no response
---

# Approval Loop

## Summary

Risky actions require an explicit mobile Approve/Deny decision before Ris proceeds, creating a hard gate around destructive, costly, production, or secret-bearing operations.

## Behavior

When Ris is about to take a risky action, it renders Approve/Deny buttons plus a text fallback. If the user does not respond, the task is parked rather than proceeding. Silence is never approval.

## Out of scope

- NOT auto-approving destructive/spend/secret actions: these categories always require the user's explicit approval.
- NOT proceeding on no response: silence parks the task.

## Open questions

- [ ] The timeout duration before an unanswered prompt parks the task is not specified, and the park-on-no-response behavior has not been verified.

## Implementation notes (optional)

Verified 2026-07-07 (the "approve-from-phone gate"): a write to a protected path (`/private/tmp/…`) triggered Hermes' Approve/Deny prompt; approving from mobile ran the command, denying from mobile blocked it. Gate armed by default via `approvals.mode: manual` in `~/.hermes/config.yaml` (values: `manual` | `smart` | `off`; `approvals.timeout` controls the park behavior — not yet exercised). Two of three acceptance criteria confirmed; timeout/park still to verify before `implemented`.

## What the gate does and does not stop

Verified against real Claude Code, not inferred:

- **Read-only commands do not stop you.** `cat`, `ls`, `head`, `tail`, `wc`,
  `grep`, `rg`, `stat`, `file`, `which` and `echo` are passed via
  `--allowedTools`. The first live run gated a `cat` and cost 11 seconds of
  someone's attention for nothing.
- **Compound commands still stop you.** Claude Code matches a prefix, so
  `cat x; node -e "..."` reaches the gate. That is correct: the compound form
  is exactly how a read carries a write.
- **`node`, `find`, `sed`, `xargs` and `python` are deliberately absent** from
  the allowlist. `node -e` writes files and opens sockets, `find -exec` runs
  anything, `sed -i` edits in place. A command that looks like a read is not
  a read.
- **In-project file changes are not gated at all.** `acceptEdits` permits them
  before the prompt tool is ever consulted, including `rm` inside the
  worktree. The gate catches what that mode will not decide alone — writes
  outside the project, and unusual or compound commands.
- **`--permission-mode auto` is not an option.** It stops gating out-of-project
  writes and file deletion entirely; it is `bypassPermissions` with a
  friendlier name.

An unattended run (`--unattended`, or the checkbox on the launch form) omits
the gate altogether, because a prompt nobody will answer stalls for the full
timeout and then fails closed.
