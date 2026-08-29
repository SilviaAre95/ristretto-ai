# Ristretto (Ris) — Feature Bank

Source of truth for what this product **does** and **does not** do. Every code change affecting `/src`, `/app`, `/lib`, `/api`, `/components`, `/pages`, or equivalent must preflight against this bank.

## How to use

- Agents: read this file first. Load the relevant feature file(s) before editing code.
- Humans: add new features via the `feature-bank` skill scaffolder, not by hand-editing (unless you like inconsistency).
- Spec changes require the diff-first escape hatch. See the skill.

## Features

| ID | Title | Status | Summary | Top non-goals |
|----|-------|--------|---------|---------------|
| `slack-gateway` | Slack Gateway | implemented | Ris talks to one allowlisted user in Slack over Socket Mode. | NOT public/multi-user; NOT other chat platforms in V0 |
| `ris-persona` | Ris Persona | implemented | Assistant identifies and behaves as "Ris", per SOUL.md. | NOT a generic assistant voice; NOT changing identity per session |
| `local-brain` | Local Brain | implemented | `qwen3.6:35b-mlx` orchestrates locally; `qwen3.6:27b-coding-nvfp4` is the local coder across four tiers. | NOT cloud LLM for orchestration in V0; NOT the primary coding brain |
| `linear-integration` | Linear Integration | implemented | Ris reads and writes one configured Linear team via MCP. | NOT acting on other teams; NOT auto-closing issues without instruction |
| `config-in-repo` | Config In Repo | implemented | Hermes config versioned in repo and symlinked; secrets stay local. | NOT committing secrets; NOT versioning the Hermes engine code or runtime state |
| `morning-brief` | Morning Brief | implemented | 8am cron posts a prioritized brief to the configured Slack channel. | NOT acting on the board automatically; NOT posting when nothing is new |
| `evening-report` | Evening Report | proposed | A 6pm cron summarizes the day's shipped work, PRs, and blockers. | NOT changing issue states without a real event; NOT duplicating the morning brief |
| `approval-loop` | Approval Loop | in-progress | Risky actions require an explicit mobile Approve/Deny decision. | NOT auto-approving destructive/spend/secret actions; NOT proceeding on no response |
| `autonomous-coding` | Autonomous Coding | in-progress | Ris runs a selected coding flow on a branch and opens a PR. | NOT auto-merging; NOT acting on employer systems |
| `custom-model-flows` | Custom Model Flows | in-progress | Validated stages route planning, coding, review, verification, and PR work. | NOT arbitrary commands; NOT storing credentials; NOT auto-merging |
| `always-on-service` | Always-On Service | implemented | Gateway runs as launchd service; Lungo holds the wake assertion. | NOT changing pmset without approval; verify Lungo after reboot |
| `telegram-ops-lane` | Telegram Ops Lane | in-progress | Identity-locked Telegram daemon relays Claude Code's own `ask` prompts to your phone. | NOT a second allowlist system; NOT auto-run; NOT inbound networking |
| `event-spine` | Event Spine | in-progress | Pipeline events in Ristretto's own log; `preflight` proves a repo is loop-capable; `gc` reclaims finished worktrees. | NOT writing into Hermes' schema; NOT a UI in V1; NOT removing worktrees with uncommitted work |
| `fleet-view` | Fleet View | in-progress | Dashboard over the board and event log, bound to the tailnet; stop, unblock, and ask Ris. | NOT launching work; NOT public ingress; NOT implying a heartbeat Hermes does not expose |
| `flow-enforcement` | Flow Enforcement | implemented | A loop task cannot be completed unless its loop actually ran. | NOT gating non-loop tasks; NOT relying on the event log; NOT blocking edits, only completion |

<!-- Append new rows above this comment. Keep the summary column ≤ 15 words. -->

## Deprecated

| ID | Title | Deprecated on | Replaced by |
|----|-------|---------------|-------------|
| | | | |

## Conventions

- **Feature IDs**: kebab-case, domain-prefixed (`auth-login`, `billing-invoice`, `search-filters`).
- **Status values**: `proposed` → `in-progress` → `implemented` → `deprecated`.
- **Non-goals**: if empty, the feature has no boundaries. Fix that.
