---
id: local-brain
title: Local Brain
status: implemented  # proposed | in-progress | implemented | deprecated
created_at: 2026-07-05
last_modified: 2026-07-18
owner: project
depends_on: []
acceptance_criteria:
  - Brief/chat/tool-calls run through the local model
  - $0 marginal cost
  - No cloud LLM call for orchestration
non_goals:
  - NOT cloud LLM for orchestration in V0
  - NOT forcing one coding model for every task
---

# Local Brain

## Summary

Orchestrator reasoning defaults to local `qwen3.6:27b` through Ollama, keeping chat, briefs, and tool decisions on the user's machine. Coding flows may use Claude, Codex, the local coder, or a validated combination. `RIS_LOCAL_LOOP_MODEL` overrides the public `qwen3-coder:30b` coding default.

## Behavior

Orchestrator-level reasoning is routed through the configured Ollama model. No cloud model is required for these paths, so day-to-day orchestration can have no marginal model cost.

Heavy local code loops use the environment-selected coder without changing the orchestrator. The public baseline limits kanban workers to one at a time because concurrent local models can exhaust memory and thermal headroom.

## Out of scope

- NOT cloud LLM for orchestration in V0: no OpenAI/Anthropic/etc. API calls are made for the chat/brief/tool-call loop; this is deliberate to keep marginal cost at $0.
- NOT forcing one coding model for every task: `classic` remains the default, while explicit named flows can use the local coder for build, repair, review, or the entire task.

## Open questions

## Implementation notes (optional)

Hermes v0.18.0 orchestrator configured with brain `qwen3.6:27b` served locally via Ollama.

Suggested model roles:

| Model | Role |
|---|---|
| `qwen3.6:27b` | Default always-on orchestrator |
| `qwen3-coder:30b` | `run-loop.sh` fallback when `RIS_LOCAL_LOOP_MODEL` is unset |
| `$RIS_LOCAL_LOOP_MODEL` | Optional machine-local coding override |

Model-change checklist:

1. `ollama pull <candidate>`
2. Temporarily switch with `/model <candidate> --provider ollama --session`
3. Verify Slack reply, Linear tool call, and morning-brief dry run
4. Run one low-stakes repo task
5. Watch memory/thermal behavior before editing `hermes/config.yaml`
