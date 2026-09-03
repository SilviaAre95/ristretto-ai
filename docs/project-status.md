# Project Status

> **Superseded in part.** `docs/nemo-architecture.md` re-frames this project:
> Ristretto is Nemo, a personal assistant that can write code, rather than a
> coding harness with a chat surface. The workshop described below is intact
> and carried forward; the centre of the system moves from runs to
> conversation, Linear and the vault.


Ristretto is preparing its first public `0.1.0` release.

## Implemented

- Hermes-based local orchestrator baseline.
- Slack conversation and approval surface.
- Linear issue integration and stateful morning-brief precheck.
- Durable feature-branch coding workers with verified orphan cleanup.
- `classic`, `balanced`, `quality`, `local`, and custom coding flows.
- Configuration validation, provider doctor, development bootstrap, CI, and
  tagged-release workflow.

## Release work

- Verify the exported snapshot in a fresh checkout environment.
- Dogfood one supervised non-classic coding flow.
- Cut `v0.1.0` only after `make check` and `make public-check` pass.

Personal instance state, issue exports, channel IDs, repository mappings, and
runtime logs intentionally live outside this public repository.

## Nemo (exploration)

`docs/nemo-feasibility.md` — feasibility check on giving Ristretto a body, a
push-to-talk input and an on-screen presence. Not scheduled. Records the
resolved rule for voice and authority (voice composes, a click commits) and
notes that the launch surface is a prerequisite.
