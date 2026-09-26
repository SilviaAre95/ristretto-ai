---
id: custom-model-flows
title: Custom Model Flows
status: in-progress  # proposed | in-progress | implemented | deprecated
created_at: 2026-07-18
last_modified: 2026-09-24
owner: project
depends_on: [autonomous-coding]
acceptance_criteria:
  - Named flows select a provider independently for each stage
  - Read-only plan and review stages cannot mutate the worktree
  - Artifacts pass explicitly between ordered stages
  - Verification must pass before the final PR stage
  - Users can add a valid flow in YAML without changing runner code
  - Existing classic tasks remain backward compatible
  - Every flow, classic included, starts from every surface through one path
  - A classic run's model tier survives a relaunch
  - No shipped flow routes a mutating stage to a local model
  - Every stage spawn carries a filesystem scope, or the launch is refused
    (pending `filesystem-scoping`, which is `proposed`)
  - A staged flow's effective permissions come from Cuzam, never from a
    settings file committed in the repository being worked on (pending
    `filesystem-scoping`; `classic` is excluded by that spec's rollout)
non_goals:
  - NOT allowing arbitrary unvalidated runner commands
  - NOT storing provider credentials in the repository or UI
  - NOT merging pull requests automatically
  - NOT trading cloud spend for local compute
---

# Custom Model Flows

## Summary

Cuzam can run a coding task with a named, validated sequence of model
stages. Two included flows trade **scrutiny** for speed. `full` is plan, build,
review, repair, deterministic verify, PR — Opus plans and reviews, Sonnet
builds and repairs, Haiku opens the PR, and the reviewer is never the model
that wrote the code. `short` is plan, build, verify, PR for low-risk changes:
Opus plans, Sonnet builds, Haiku opens the PR. `short` has no review stage, so
the deterministic `.cc-verify` gate is the only thing between generated output
and the branch — which is why `full` is the default and `short` is opt-in.
Opus plans both, because in `short` the plan is the only judgement stage.
Model choice per stage is ordinary cost-fitting inside Claude. The existing
Claude `/loop-dev` behavior remains available as `classic`.

The earlier `tier0`–`tier3` ladder graded how much Claude a run used, with the
token-heavy build on a local coder. That premise was retired on 2026-09-23 and
the tiers are removed; the axis they measured no longer exists.

## Behavior

The public contract lives in `cuzam.yaml`. A flow is an ordered list of
stages with a stable id, role, provider, mutation permission, input artifacts,
output artifact, and optional timeout. Configuration validation rejects
unknown providers, unsafe names, missing artifacts, mutating plan/review stages,
and a PR stage anywhere except the end.

Each model stage runs as a separate process. Plans and reviews use read-only
runner permissions. Build, repair, and PR stages may write only when their
stage explicitly sets `mutates: true`. Stage outputs and logs are stored under
`.cuzam/runs/<task-id>/`; credentials are resolved from environment
variables and are never written into the resolved flow output.

Task requests may select a flow explicitly, for example "do PROJ-123 on
short." There is one entry point. Every surface — `cuzam launch`, the Slack
`!zam-start` command, the launch form and the `durable-dev` skill — calls
`launch`, which spawns the flow itself. A surface that sends no flow gets the
configured `default_flow`, `full` as shipped; `durable-dev` asks for `classic`
explicitly, preserving the proven `/loop-dev` path for work that arrives as
chat rather than as a launch.

`classic` is spawned as `run-loop.sh`, every other flow as `cuzam.runner`, and
that is the only place the distinction is made. It is made on the flow's
`builtin` key, never on its name, so a fourth flow cannot land on the wrong
side of it by being called something unexpected. A classic run carries an
optional model tier (`sonnet`, `haiku`, `opus`) written into the task body, so
a relaunch runs what the first attempt ran; a staged flow takes its models
from its stages and is given no tier.

There is no longer a way to ask for a local coding run: `local-brain` is the
only local provider a flow can name, and no shipped flow gives it a mutating
stage.

## Custom flow example

Add another entry under `flows` without changing Python code:

```yaml
flows:
  my-flow:
    description: My project-specific pipeline.
    stages:
      - id: plan
        role: plan
        provider: claude
        mutates: false
        output: plan.md
      - id: build
        role: build
        provider: claude
        mutates: true
        inputs: [plan.md]
        output: build.md
      - id: review
        role: review
        provider: codex
        mutates: false
        inputs: [plan.md, build.md]
        output: review.md
      - id: verify
        role: verify
        provider: builtin
        mutates: false
        output: verify.txt
      - id: finish
        role: pr
        provider: claude
        mutates: true
        inputs: [review.md, verify.txt]
        output: finish.md
```

Run `cuzam validate` and `cuzam flow show my-flow` before queueing it.
The deterministic verification command comes from the repository-owned
`.cc-verify` file, not from user or issue text. Its SHA-256 digest is pinned
before the first stage starts; if a build or repair stage changes the file,
Cuzam refuses to execute it.

Provider secrets must be referenced through `auth_token_env`. Literal tokens
are rejected; the sole literal exception is the non-secret `ollama` placeholder
used by the local compatibility API.

## Out of scope

- NOT executing arbitrary provider command strings from YAML.
- NOT putting credentials in configuration, task artifacts, or the future UI.
- NOT auto-merging: the terminal stage can open or update a feature-branch PR,
  but the user remains the merge authority.
- NOT trading cloud spend for local compute: flows are graded by scrutiny, not
  by how much of the run avoids Claude.

## Open questions

- Should a future schema version support conditional repair stages based on a
  machine-readable review result?
- Which local API should the menu-bar editor use to queue and monitor flows?
