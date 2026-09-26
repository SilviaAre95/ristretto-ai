---
id: custom-model-flows
title: Custom Model Flows
status: in-progress  # proposed | in-progress | implemented | deprecated
created_at: 2026-07-18
last_modified: 2026-09-26
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
  - A provider declares its hosting; nothing infers it from the presence of a
    `base_url`, and nothing inspects the host a `base_url` names
  - A provider carrying a `base_url`, literally or through `base_url_env`,
    without a declared hosting is a configuration error that names the fix
  - A misspelled provider setting is refused rather than ignored
  - No shipped flow routes a mutating stage to a provider declared
    `hosting: local`
  - A provider declared `hosting: third-party` may take a mutating stage
  - A provider declared non-vendor whose endpoint or credential does not
    resolve is refused, never run against the vendor endpoint or reached with
    the environment's own credentials
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
  - NOT deciding a provider's hosting by inspecting its URL
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

### Provider hosting

Every provider declares where it is served, because the two questions a stage
spawn needs answered are different questions and only one of them can be read
off a URL. `hosting` is one of:

- **`vendor`** — the runner's own endpoint, reached on the operator's own
  subscription. No `base_url`. This is the default when `hosting` is absent, so
  the common case stays silent.
- **`third-party`** — someone else's hosted endpoint. Requires a `base_url` and
  a real credential through `auth_token_env`. This is what lets a stage run on
  a model the runner's own subscription does not serve, so that a run's
  token-heavy stages need not all be spent against one plan's capacity.
- **`local`** — served by this machine, which in practice means a loopback
  `base_url`. It is the only hosting allowed to use the non-secret `ollama`
  placeholder as a literal `auth_token`. That the address is in fact on this
  machine is what the operator asserts by declaring it, and is not checked; see
  below.

`hosting` is **required whenever a base URL is configured — literally as
`base_url` or indirectly as `base_url_env`**, so only the ambiguous case has to
answer, and such a provider without it is a configuration error that names the
fix rather than one quietly filed as `vendor`. The indirect form counts because
it is resolved from the environment after validation has run: a provider
declaring only `base_url_env` has no `base_url` at the moment it is checked and
acquires one before it is used, which is the same misfiling by a slower route.

Provider settings are a closed set, so a misspelled one is refused instead of
ignored. Without that, `hostng: local` is not a local provider — it is a
`vendor` provider carrying an ignored key, eligible for exactly the mutating
stage the declaration was written to refuse.

**Nothing inspects the host itself.** A validator deciding whether a URL is
"really" local would be right on a loopback address and wrong, silently and
only on someone else's network, for a private range, a VPN address, an SSH
tunnel or a hostname that resolves differently per machine. The operator knows
where their endpoint is; the config records what they said.

The distinction earns its keep in two places that were previously one. A flow
stage gets `--strict-mcp-config`, `--add-dir` and
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` for **any** provider that is not the
vendor's endpoint, because that is about MCP discovery hanging against a
non-Anthropic host and applies equally to a hosted one. The prohibition on a
mutating stage, by contrast, is about **this machine's** models specifically —
see `local-brain` — and applies only to `hosting: local`.

This is the flow runner's behaviour, not every spawn's: the assistant loop sets
the base URL for the same providers and passes none of the three. Since
`instance.assistant_provider` points at a local provider, that path runs the
configuration described here as hanging indefinitely, and does not hang — which
means the account above is incomplete rather than wrong, and is recorded as an
open question rather than tidied over.

So there is no longer a way to ask for a *locally served* coding run: no
shipped flow gives a mutating stage to a provider declared `hosting: local`. A
provider declared `third-party` may take one. Whether it should is a question
for the deterministic verify gate on the run in question, not for the
configuration schema.

A provider entry in the user layer replaces the shipped entry of that name
whole rather than merging field by field, so a user file holding its own copy of
a `base_url` provider must carry `hosting` itself. Validation fails closed and
names the field, `cuzam doctor` reports it per provider, and `cuzam migrate`
shows it as drift against the shipped entry and adopts the shipped version with
`--adopt --force`.

Declaring an endpoint is not the same as having one. A provider declared
`third-party` whose credential does not resolve, or whose `base_url_env` is
unset at launch, is refused at resolution rather than run: the first would reach
someone else's host carrying whatever credentials the operator's own environment
holds, and the second would silently run against the vendor endpoint while the
config said otherwise.

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
used by the local compatibility API, which is available only to a provider
declared `hosting: local`. A `third-party` provider holds a real credential and
so must name it through `auth_token_env`.

## Out of scope

- NOT executing arbitrary provider command strings from YAML.
- NOT putting credentials in configuration, task artifacts, or the future UI.
- NOT auto-merging: the terminal stage can open or update a feature-branch PR,
  but the user remains the merge authority.
- NOT trading cloud spend for local compute: no model served by this machine
  takes a coding stage. That is the whole of this boundary. A hosted
  open-weight model is not local compute, so a flow may route a build to a
  `third-party` provider; the verify gate still decides whether that output
  reaches a branch. This bullet used to add "flows are graded by scrutiny, not
  by how much of the run avoids Claude", which said the same thing while the
  only alternative to Claude was a model on this machine. It does not say the
  same thing now, and that sentence is withdrawn.
- NOT deciding a provider's hosting by inspecting its URL: `hosting` is
  declared. A guess would be wrong silently and only on some networks.

## Open questions

- Should the local-mutating-stage prohibition bind a user's own flows, not just
  the shipped ones? It is enforced by a test over `cuzam.yaml`, so a user flow
  giving `local-brain` a `mutates: true` stage validates cleanly today. Now that
  hosting is declared, `validate_config` could express it beside the
  "review stages must be read-only" rule. Against: the shipped config is what
  this project is responsible for, and an operator who declares a provider local
  and then asks it to build has said two things and may mean the second.
- Should the `ollama` placeholder be available to `hosting: third-party`? A
  credential-free Ollama on a private range or a VPN address is a case
  `_hosting`'s own docstring names as legitimate, and it is currently
  unconfigurable without either declaring it `local` — which would be a lie that
  costs it any mutating stage — or putting the literal string `ollama` in an
  environment variable.
- Why does the assistant loop not need what every flow stage needs? It sets
  `ANTHROPIC_BASE_URL` for a provider with its own endpoint and passes none of
  `--strict-mcp-config`, `--add-dir` or
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, yet `instance.assistant_provider`
  points at a local provider and that path does not hang. Either the hang needs
  a narrower description than "any non-vendor endpoint" or the assistant loop is
  one Claude Code release away from the failure that cost `tier1` an hour.
- Should a future schema version support conditional repair stages based on a
  machine-readable review result?
- Which local API should the menu-bar editor use to queue and monitor flows?
