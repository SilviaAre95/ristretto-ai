---
id: local-brain
title: Local Brain
status: implemented  # proposed | in-progress | implemented | deprecated
created_at: 2026-07-05
last_modified: 2026-09-26
owner: project
depends_on: []
acceptance_criteria:
  - Brief/chat/tool-calls run through the local model
  - $0 marginal cost
  - No cloud LLM call for orchestration
  - No model served by this machine writes to a repository
non_goals:
  - NOT cloud LLM for orchestration in V0
  - NOT writing production code: no model served by this machine takes a coding
    stage
  - NOT reviewing or verifying generated code: nor a review or verify stage
---

# Local Brain

## Summary

Orchestrator reasoning defaults to local `qwen3.6:35b-mlx` through Ollama, keeping chat, briefs, and tool decisions on the user's machine. **Coding runs on Claude.** The dividing line is bounded transformation — summarise, extract, classify, rank, reformat, where the output shape is known and a wrong answer is cheap and visible — against unbounded judgement, where subtle wrongness compounds silently. `ZAM_LOCAL_BRAIN_MODEL` overrides the brain.

## Behavior

Orchestrator-level reasoning is routed through the configured Ollama model. No cloud model is required for these paths, so day-to-day orchestration can have no marginal model cost.

The public baseline limits kanban workers to one at a time because concurrent local models can exhaust memory and thermal headroom.

No model served by this machine writes to a repository, and none stands between generated output and a branch. A local generator paired with a local verifier has been observed reporting success on zero work, so review and verify are Claude or the deterministic `.cc-verify` gate, never a local model.

"Local" here means served by this machine, and that is now a declaration rather than a deduction: a provider says `hosting: local`, and `custom-model-flows` carries the field. The evidence behind these boundaries was gathered against models running on this hardware, and it is the hardware that the argument turns on — small quantised weights, a context window traded away for memory headroom, and a verifier sharing both. It says nothing about an open-weight model of a different size served by someone else, and reading it as though it did was an accident of the config schema: while the only provider carrying a `base_url` was Ollama on the loopback, "has a `base_url`" and "runs here" were the same set. They are not any more, and these non-goals apply to the declared-local set, not to the `base_url` set.

## Out of scope

- NOT cloud LLM for orchestration in V0: no OpenAI/Anthropic/etc. API calls are made for the chat/brief/tool-call loop; this is deliberate to keep marginal cost at $0.
- NOT writing production code: retired 2026-09-23. The original premise was that a local coder would do the token-heavy build while Claude supervised. Every attempt died in the build stage, so the `local-coder` provider and the `tier1`–`tier3` flows are gone and no shipped flow routes a build, repair or PR stage to a provider declared `hosting: local`. The judgement was about quality, measured on this machine's models; it is not a judgement about hosted open-weight models, which `custom-model-flows` allows a flow to give a mutating stage and which nothing here has tested.
- NOT reviewing or verifying generated code: verifier blind spots rise as the generator improves, so nothing served by this machine goes between generated output and the repository.

## Open questions

- May a model served by this machine write something that is not code — release
  notes, a changelog entry, a PR description? The boundary enforced today is
  coarser than the one argued for: the acceptance criterion says a local model
  writes nothing to a repository, and the guard is on a stage's `mutates` flag,
  which is any write at all. The evidence from 2026-09-23 was about builds, and
  a local model is already trusted to summarise and rank in the assistant path,
  which is the same bounded-transformation shape as a changelog entry. What is
  missing is a role narrower than `mutates: true` to hang it on: there is no
  `docs` role, and the `pr` role bundles writing the description with pushing
  the branch. Until there is one, the coarse rule stands.

## Implementation notes (optional)

Hermes orchestrator configured with brain `qwen3.6:35b-mlx` served locally via Ollama's MLX runner (Apple Silicon, Ollama >= 0.19).

Suggested model roles:

| Model | Role |
|---|---|
| `qwen3.6:35b-mlx` | Default always-on orchestrator and the `local-brain` flow provider: MoE, fast, 256k context |
| `$ZAM_LOCAL_BRAIN_MODEL` | Machine-local override |

The hardware floor followed from the retired premise. With coding on Claude and
utility work on a small local model, the large-memory requirement drops a long
way; `local-brain` is the only provider Cuzam ships declaring `hosting: local`.

Model-change checklist:

1. `ollama pull <candidate>`
2. Temporarily switch with `/model <candidate> --provider ollama --session`
3. Verify Slack reply, Linear tool call, and morning-brief dry run
4. Run one low-stakes repo task
5. Watch memory/thermal behavior before editing `hermes/config.yaml`
