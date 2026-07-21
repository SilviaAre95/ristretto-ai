---
name: issue-closeout
description: Use when a task or PR has just been merged (the user says "merged"/"merged it", or you confirm a merge landed) — run the post-merge closeout: move the Linear issue to Done, comment the resolution, log to the configured vault, create follow-ups, and PROPOSE (never auto-do) backlog reconciliation.
version: 1.0.0
author: Silvia Arellano
license: MIT
metadata:
  hermes:
    tags: [linear, closeout, post-merge, ops, workflow, vault]
    related_skills: [feature-bank]
---

# Issue Closeout

Merging the code is not closing the loop. After a task's PR is merged, run this closeout every time, then post ONE terse Slack line. Detail lives in Linear and the Obsidian vault — never in the Slack thread.

Run this yourself with your Linear tools and file access — do NOT delegate it to Claude Code.

## Steps

1. **Linear → Done.** Set the merged issue's state to Done (the team's completed-type state — do not assume a state name; this team has no "In Review"). Done when: the issue's status is Done.

2. **Resolution comment.** Add a comment on the Linear issue: 1–3 lines on what shipped, the bare PR URL, and any decision worth recording. Done when: the comment is created.

3. **Project Changelog (always).** Resolve the vault root with `vault="$(ristretto instance get knowledge_vault)"` and append one dated line to `$vault/02-Projects/<project>.md` under its `## Changelog` heading, matching the existing line style:
   `- <YYYY-MM-DD> — <ISSUE-KEY>: <one-line summary> (PR #N)`
   If the note has no `## Changelog` section, add one at the end. If you can't map the issue to a project note, ask the user rather than guess. Done when: the line is appended.

4. **Knowledge note (only if reusable).** If the task produced a genuinely reusable insight or a non-obvious gotcha (a pattern, a footgun, a decision worth reusing across projects), write a standalone topic note `$vault/04-Knowledge/<kebab-topic>.md`. Skip routine changes — capture signal, not noise. Done when: a note is written, or you've explicitly judged it not reusable.

5. **Follow-ups + reconcile.**
   - **Follow-ups (safe to create):** if the fix surfaced genuine new work, create follow-up Linear issue(s) in the same project, referencing the closed issue.
   - **Reconcile (PROPOSE only):** check whether this fix makes any existing issue obsolete, redundant, or in need of an update. List those for the user and wait for a decision. NEVER close, cancel, or rewrite an existing issue on your own judgment.
   Done when: follow-ups are created (if any), reconciliation is proposed (if any); otherwise say "no follow-ups, nothing to reconcile."

6. **Report.** Post ONE terse Slack line summarizing the closeout, e.g. "Closed out PROJ-42 — Done, logged, 1 follow-up proposed." Nothing more in the thread.

## Guardrails

- NEVER auto-close, cancel, or rewrite an existing issue — reconciliation is propose-only.
- Vault = signal, not noise: the project Changelog gets a line every time; a 04-Knowledge note only when genuinely reusable.
- Keep Slack terse; the detail belongs in Linear + the vault.
