---
id: local-brain
title: Local Brain
status: implemented  # proposed | in-progress | implemented | deprecated
created_at: 2026-07-05
last_modified: 2026-08-24
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

Orchestrator reasoning defaults to local `qwen3.6:35b-mlx` through Ollama, keeping chat, briefs, and tool decisions on the user's machine. Coding flows may use Claude, the local brain, the local coder, or a validated combination (`tier0` through `tier3`). `RIS_LOCAL_LOOP_MODEL` overrides the public `qwen3.6:27b-coding-nvfp4` coding default; `RIS_LOCAL_BRAIN_MODEL` overrides the brain inside flows.

## Behavior

Orchestrator-level reasoning is routed through the configured Ollama model. No cloud model is required for these paths, so day-to-day orchestration can have no marginal model cost.

Heavy local code loops use the environment-selected coder without changing the orchestrator. The public baseline limits kanban workers to one at a time because concurrent local models can exhaust memory and thermal headroom.

## Out of scope

- NOT cloud LLM for orchestration in V0: no OpenAI/Anthropic/etc. API calls are made for the chat/brief/tool-call loop; this is deliberate to keep marginal cost at $0.
- NOT forcing one coding model for every task: `classic` remains the default, while explicit named flows can use the local coder for build, repair, review, or the entire task.

## Open questions

## Implementation notes (optional)

Hermes orchestrator configured with brain `qwen3.6:35b-mlx` served locally via Ollama's MLX runner (Apple Silicon, Ollama >= 0.19).

Suggested model roles:

| Model | Role |
|---|---|
| `qwen3.6:35b-mlx` | Default always-on orchestrator and the `local-brain` flow provider: MoE, fast, 256k context |
| `qwen3.6:27b-coding-nvfp4` | `local-coder` flow provider and `run-loop.sh` fallback when `RIS_LOCAL_LOOP_MODEL` is unset: dense, strongest local coder |
| `qwen3-coder-next:q4_K_M` | Optional large-project coder, selected per run with `RIS_LOCAL_LOOP_MODEL` |
| `$RIS_LOCAL_LOOP_MODEL` / `$RIS_LOCAL_BRAIN_MODEL` | Machine-local overrides |

Reviewer is never builder: the brain reviews what the coder built, in every tier.

Model-change checklist:

1. `ollama pull <candidate>`
2. Temporarily switch with `/model <candidate> --provider ollama --session`
3. Verify Slack reply, Linear tool call, and morning-brief dry run
4. Run one low-stakes repo task
5. Watch memory/thermal behavior before editing `hermes/config.yaml`
