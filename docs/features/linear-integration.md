---
id: linear-integration
title: Linear Integration
status: implemented  # proposed | in-progress | implemented | deprecated
created_at: 2026-07-05
last_modified: 2026-07-05
owner: project
depends_on: [local-brain]
acceptance_criteria:
  - Lists/reads issues in the configured team
  - Can create/update issues
  - Brief pulls prioritized issues
non_goals:
  - NOT acting on unconfigured teams
  - NOT auto-closing issues without instruction
---

# Linear Integration

## Summary

Ris reads and writes one configured Linear team via MCP. It can surface priorities and, with instruction, create or update issues without requiring manual copying.

## Behavior

Through Linear MCP, Ris lists and reads issues for `instance.linear_team`. The user can request issue creation or updates through the same connection. The morning brief pulls a prioritized view of that team. Ris never operates on another team and never resolves an issue on its own initiative.

## Out of scope

- NOT acting on unconfigured teams: other teams in the same Linear workspace remain out of scope.
- NOT auto-closing issues without instruction: Ris never marks an issue done/closed as a side effect of a brief or background process — only when explicitly told to.

## Open questions

## Implementation notes (optional)

Linear is reached through MCP and scoped by the user-owned Ristretto configuration.
