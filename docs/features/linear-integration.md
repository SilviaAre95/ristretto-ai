---
id: linear-integration
title: Linear Integration
status: implemented  # proposed | in-progress | implemented | deprecated
created_at: 2026-07-05
last_modified: 2026-09-23
owner: project
depends_on: [local-brain]
acceptance_criteria:
  - Lists/reads issues in the configured team
  - Can create/update issues
  - Brief pulls prioritized issues
  - No path reaches Linear by importing Hermes internals
non_goals:
  - NOT acting on unconfigured teams
  - NOT auto-closing issues without instruction
  - NOT a second Linear credential for the same read
---

# Linear Integration

## Summary

Ris reads and writes one configured Linear team. It can surface priorities and, with instruction, create or update issues without requiring manual copying. There are two routes to Linear and the split is deliberate: **MCP** for anything conversational or mutating, and Ristretto's **own GraphQL client** for the unattended reads that must not depend on an agent being alive.

## Behavior

Through Linear MCP, Ris lists and reads issues for `instance.linear_team`, and the user can request issue creation or updates through the same connection.

The morning brief and a flow's context assembly do not use MCP. They call `ristretto/context.py`, which queries Linear's GraphQL API directly with `LINEAR_API_KEY` — `linear_issue()` for one issue's body, `linear_issues()` for the team's open board, surfaced as `ristretto issues`. Ris never operates on another team and never resolves an issue on its own initiative.

## Out of scope

- NOT acting on unconfigured teams: other teams in the same Linear workspace remain out of scope.
- NOT auto-closing issues without instruction: Ris never marks an issue done/closed as a side effect of a brief or background process — only when explicitly told to.
- NOT a second credential: the GraphQL path reuses `LINEAR_API_KEY`, already required by context assembly. The split is about *how* Linear is reached, not about holding two sets of keys.

## Open questions

## Implementation notes (optional)

Both routes are scoped by the user-owned Ristretto configuration. MCP is configured at `hermes/config.yaml:69`.

The brief's precheck used to reach Linear a third way: `from tools.registry import registry`, executed inside a Hermes process to borrow Hermes' own Linear MCP tool. That was the only import of Hermes internals anywhere in this project. A registry entry is a private interface — nothing warns when an engine upgrade renames one — and there is no `hermes mcp call` to reach it as an interface instead. The precheck now shells `ristretto issues`, the same way it already shelled `ristretto instance get` for the team key: one Linear client, one process boundary.
