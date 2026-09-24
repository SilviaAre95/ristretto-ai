---
id: local-brain
title: Local Brain
status: implemented  # proposed | in-progress | implemented | deprecated
created_at: 2026-07-05
last_modified: 2026-09-23
owner: project
depends_on: []
acceptance_criteria:
  - Brief/chat/tool-calls run through the local model
  - $0 marginal cost
  - No cloud LLM call for orchestration
  - No local model writes to a repository
non_goals:
  - NOT cloud LLM for orchestration in V0
  - NOT writing production code
  - NOT reviewing or verifying generated code
---

# Local Brain

## Summary

Orchestrator reasoning defaults to local `qwen3.6:35b-mlx` through Ollama, keeping chat, briefs, and tool decisions on the user's machine. **Coding runs on Claude.** The dividing line is bounded transformation — summarise, extract, classify, rank, reformat, where the output shape is known and a wrong answer is cheap and visible — against unbounded judgement, where subtle wrongness compounds silently. `ZAM_LOCAL_BRAIN_MODEL` overrides the brain.

## Behavior

Orchestrator-level reasoning is routed through the configured Ollama model. No cloud model is required for these paths, so day-to-day orchestration can have no marginal model cost.

The public baseline limits kanban workers to one at a time because concurrent local models can exhaust memory and thermal headroom.

No local model writes to a repository, and none stands between generated output and a branch. A local generator paired with a local verifier has been observed reporting success on zero work, so review and verify are Claude or the deterministic `.cc-verify` gate, never a local model.

## Out of scope

- NOT cloud LLM for orchestration in V0: no OpenAI/Anthropic/etc. API calls are made for the chat/brief/tool-call loop; this is deliberate to keep marginal cost at $0.
- NOT writing production code: retired 2026-09-23. The original premise was that a local coder would do the token-heavy build while Claude supervised. Every attempt died in the build stage, so the `local-coder` provider and the `tier1`–`tier3` flows are gone and no shipped flow routes a build, repair or PR stage to a local model.
- NOT reviewing or verifying generated code: verifier blind spots rise as the generator improves, so nothing local goes between generated output and the repository.

## Open questions

## Implementation notes (optional)

Hermes orchestrator configured with brain `qwen3.6:35b-mlx` served locally via Ollama's MLX runner (Apple Silicon, Ollama >= 0.19).

Suggested model roles:

| Model | Role |
|---|---|
| `qwen3.6:35b-mlx` | Default always-on orchestrator and the `local-brain` flow provider: MoE, fast, 256k context |
| `$ZAM_LOCAL_BRAIN_MODEL` | Machine-local override |

The hardware floor followed from the retired premise. With coding on Claude and
utility work on a small local model, the large-memory requirement drops a long
way; `local-brain` is the only local provider a flow can still name.

Model-change checklist:

1. `ollama pull <candidate>`
2. Temporarily switch with `/model <candidate> --provider ollama --session`
3. Verify Slack reply, Linear tool call, and morning-brief dry run
4. Run one low-stakes repo task
5. Watch memory/thermal behavior before editing `hermes/config.yaml`
