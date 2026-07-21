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
