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

## Waiting for you does not spend the stage budget

A stage's budget measures working time. The clock stops while a permission
request is outstanding and resumes when you answer, so taking twelve minutes
to look at a prompt costs the run twelve minutes of wall clock and nothing of
its budget.

This was not always true, and the failure it caused was worth recording. Run
67 asked seven times during one build stage and spent 3437 of its 3600
seconds blocked — 163 seconds of actual work — then died reporting "timed out
with nothing written". The more carefully the agent asked, the more certainly
it failed, which is the opposite of what a gate is for. It was misdiagnosed
three times as a slow model before anyone read the approvals table.

Two details that are not obvious:

- **Overlapping waits count once.** Claude Code asks for several tool calls in
  one turn, so two prompts are often outstanding together. Run 67's own rows
  add up to 3766 seconds inside a 3600-second hour; what the stage lost is the
  union of the intervals, not their sum.
- **The forgiveness is bounded** at four expired approvals' worth (two hours).
  Past that the stage gives up and says so, rather than holding a worktree and
  a Hermes claim for an operator who has gone to bed.

The failure reason distinguishes the two cases, because they need opposite
responses — raise the budget, or answer faster:

```
build failed: timed out after 3600s of working time (57m waiting on
              approvals was not charged) — 9 file(s) kept as a WIP commit
build failed: timed out waiting on approvals: 120m unanswered, past the
              120m the stage clock will hold for
```

`stage.passed` and `stage.failed` events carry `blocked_s` alongside
`duration_s`, so a run that took 48 minutes with 40 of them waiting on you
says so on the board.

## Widening the allowlist would not have stopped those prompts

Worth recording, because the obvious reaction to "seven interruptions in one
stage" is to allow more commands, and on this evidence that would have bought
nothing while giving up something. Every one of run 67's seven requests was
classified after the fact:

- **Six were Bash, and every one was compound** — a pipe into `head`, or two
  commands joined by `;`. Five of those six already began with an allowlisted
  word (`grep`, `which`, `ls`). Claude Code matches a prefix, so the compound
  form reaches the gate by design; adding more command names to
  `READ_ONLY_TOOLS` would not have matched any of them.
- **One was a Read outside the worktree.** Scoping reads to the project would
  not have covered it either.

So the allowlist was not the cause. What the requests have in common is that
the stage was searching the operator's notes for context on its issue — and the
last one, left unanswered when the stage died, was an attempt to read a
credentials file in the home directory. The gate stopping that is the gate
working.

The interruption count is a symptom of a stage going looking for issue context
it was not given, not of a gate that asks too much. Fix the context, not the
allowlist.
