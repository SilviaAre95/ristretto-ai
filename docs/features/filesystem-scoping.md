---
id: filesystem-scoping
title: Filesystem Scoping
status: proposed  # proposed | in-progress | implemented | deprecated
created_at: 2026-09-25
last_modified: 2026-09-25
owner: project
depends_on: [autonomous-coding, custom-model-flows, approval-loop, event-spine]
acceptance_criteria:
  - "A stage process cannot read a path outside its scope: the generated
    profile, run against a file outside scope, returns a permission error"
  - The profile is written outside the worktree, so a running stage cannot widen
    the scope of its own next stage or of a resume
  - The approvals store is not writable from inside any stage's scope: a gated
    stage cannot decide its own pending request
  - "`cuzam launch` refuses before it claims the board task or cuts the
    worktree when the scope cannot be applied"
  - Every *flow* spawn path reaches `claude` with a scope — classic, every
    staged stage, the provider preflight probe, and a relaunch — or does not
    reach it at all. `cuzam chat` is excluded and tracked separately
  - The scope is computed from Cuzam's configuration only, never from files
    committed in the repository being worked on
  - The settings Cuzam supplies deny at least what the discovered settings they
    displace denied
  - No credential is reachable as a path in any stage's scope; model and
    publishing credentials arrive as environment
  - No stage's scope contains a credential directory; the ability to push and
    open a pull request arrives as environment, never as a readable path
  - An unattended run opens its pull request — scope does not depend on
    attendance in either direction
  - A denied read appears in the run's log as a denial, so a stage that dies
    on a forgotten path is diagnosable without rerunning it
non_goals:
  - NOT scoping network access — a stage that can reach the API can exfiltrate
  - NOT a replacement for the approval gate, which decides writes and commands
  - NOT enforcement inside Hermes, which stays on its own side of the line
  - NOT scoping `cuzam chat`, which is allowed no file tools at all
  - NOT a way to make a stage ask fewer questions — that is a context problem
  - NOT stopping a stage from misusing a credential it has been handed; the
    control is that it cannot go and find another one
  - NOT a cross-platform boundary in V0; the OS layer is macOS-only
test_plan:
  - "Generator, in isolation: render a profile for a fixture project, then
    `sandbox-exec -f <profile> head <file outside scope>` and require a
    non-zero exit with `Operation not permitted`. Prove it bites by widening
    the fixture's scope to include the file and watching the assertion fail."
  - "Fail-closed launch: with `sandbox-exec` masked off `PATH`, run
    `cuzam launch` against a fixture board and assert no worktree exists, no
    claim was taken, and no process was spawned."
  - "Classic argv: extend `hermes/tests/run-loop.test.sh` to require the
    profile path in the stubbed `claude` invocation, and to fail if the loop
    runs `claude` without it."
  - "Settings provenance: give a fixture repository a hostile
    `.claude/settings.json` with a wide `permissions.allow`, run a staged
    stage against it, and assert the session's effective settings are Cuzam's."
  - "End to end, the incident: drive a classic run on an issue whose context
    exists only outside the scope. Require that the run finishes, that the
    denial is in `loop.log`, and that the run did not spend its hour at
    prompts."
---

# Filesystem Scoping

## Summary

An unattended coding flow can read the operator's entire home directory. It is
launchable from four surfaces — `cuzam launch`, the dashboard form, the Slack
command and the assistant's `launch_run` tool — and on the most-used path,
`classic`, it runs
`--permission-mode acceptEdits` with no permission broker attached, so nothing
gates what it reads. This feature gives every stage a declared filesystem
scope, enforced by the operating system rather than by the agent's own
good behaviour, and refuses to start a run whose scope cannot be applied.

The incident this answers is already recorded: a build stage spent 57 minutes
of its hour at permission prompts searching the operator's notes, ending at an
attempt to read a credentials file. The gate worked. What it was being asked
for, one prompt at a time, was the whole home directory.

## Behavior

### One principle first: no credential is ever a readable path

Every credential a stage needs arrives as **environment on the process that
needs it** — the model credential and the publishing credential alike. None of
them is a path inside the scope. Claude Code supports exactly this
(`ANTHROPIC_API_KEY` or an `apiKeyHelper` supplied through `--settings`), and
the runner already does it for locally served providers.

This is not a stylistic preference. It is what makes the rest of the scope
model possible: a stage cannot be handed a directory that happens to contain a
credential, so the awkward cases below resolve the same way every time.

### The unit of scope

A stage's scope is built from these parts, and everything not in them is denied.

**Read and write:**

- the worktree, `<repo>/.worktrees/<task-id>`, which is the stage's cwd, and
  therefore its artifact directory `<worktree>/.cuzam/runs/<task-id>` — named
  because it is where `context.md` lands;
- a **private temporary directory** under the artifact directory, with `TMPDIR`
  pointed at it. Not the shared per-user `$TMPDIR`: on macOS that is one
  directory for every process the operator runs, so scoping to it would let a
  stage read and write concurrent runs' temp files and plant files that
  out-of-sandbox processes later read. `claude`, `git`, `gh` and the verify gate
  all need somewhere to write; they do not need that somewhere to be shared;
- `~/.claude/plans` and the session scratch a stage actually uses — **and
  nothing else under `~/.claude`.** The rest of that directory is denied by
  name: `.credentials.json`, `settings.json`, `projects/`, `sessions/`,
  `history.jsonl`, `plugins/` and the operator's global `CLAUDE.md`. Granting
  the directory wholesale would have been the `.git/hooks` escape again one
  bullet later — a stage that can write `~/.claude/settings.json` installs a
  `PreToolUse` hook that runs as the operator, outside the sandbox, in their
  next session — and `projects/` holds every other project's transcripts and
  memory, which is the same material the motivating incident was about;
- a narrowed set inside `<repo>/.git`: `objects/`, `worktrees/<own-task-id>/`,
  `refs/heads/<own-branch>`, `logs/`, `packed-refs`, `info/exclude`, and the
  `FETCH_HEAD`/`ORIG_HEAD` pair. `.git` cannot be excluded — a worktree's `.git`
  is a file pointing into the primary checkout's `.git/worktrees/<task-id>`, so
  a worktree-only scope breaks git outright — but it must not be granted whole,
  for two separate reasons. `hooks/` and `config` are the escape: a stage that
  writes `.git/hooks/pre-commit`, or sets `core.hooksPath`, has arranged for
  code to run as the operator on their next commit in the real checkout, and
  this feature replaces the committed settings that deny `Edit(.git/**)` today,
  so it has to carry that guarantee rather than inherit it. And `.git` is
  **shared with the primary checkout and every sibling worktree**, so an
  unnarrowed grant would let a stage write another live run's
  `worktrees/<other-task-id>/`, move the primary checkout's branch tips, or
  `git worktree prune` a concurrent run out from under itself.

**Read only:**

- a fixed *runtime set*: the interpreter, the node runtime the `claude` binary
  resolves through, and — for a dispatched flow — the pinned runtime at
  `~/.cuzam/runtime`, because `sys.executable` is its virtualenv's python;
- `<repo>/.git/config`. Readable because git reads it constantly; not writable
  because that is the escape above. The consequence is concrete and belongs in
  the stage prompt rather than being discovered at runtime: **the publishing
  stage must push without `-u`.** `git push -u` and `gh pr create` on an
  untracked branch both write `branch.<name>.remote` and `.merge` into
  `.git/config`, and with it read-only git pushes successfully and *then* exits
  non-zero on "could not lock config file" — which a `pr` stage reads as a
  failed push;
- whatever the project declares, below.

**Denied, explicitly, and this is the point:** the rest of `$HOME`, the
operator's vault, the state home, the primary checkout's working tree, and every
sibling worktree. And every credential directory — `~/.ssh`, `~/.config/gh`,
`~/.gitconfig` and `~/.claude/.credentials.json` are outside a `pr` stage's
scope as much as a `plan` stage's.

Denying `~/.gitconfig` takes the commit identity with it, and nothing in Cuzam
sets one — this checkout happens to carry a local identity, but a repository
relying on the global file would get "Author identity unknown" from the `pr`
stage's commit and from the timeout commit that preserves work. So the identity
arrives as `GIT_AUTHOR_*` and `GIT_COMMITTER_*` in the same environment as the
publishing credential. A control whose failure mode is losing an hour of work
at the commit is not one that fails closed.

### The broker cannot share the stage's sandbox

An earlier draft granted `approvals.db` and `events.db` read-write, reasoning
that the broker is an MCP subprocess of `claude` and therefore inside the scope.
That reasoning is right and the conclusion was backwards: **because** the broker
shares the stage's sandbox, granting it the store grants the stage's own Bash
tool the same access. `approvals.decide()` is a plain conditional `UPDATE`, so a
gated stage could answer its own pending request with `sqlite3` and the operator
would never see a card. The approval gate this spec promises not to replace
would instead be bypassed by the scope it grants. `events.db` is the milder
version of the same hole: forged pipeline events, reported by the fleet view and
the doorbell as fact.

So both stores stay outside the scope, and the broker stops being a subprocess
of `claude`. It becomes a process the launcher starts outside the sandbox, which
`claude` reaches over a socket or local HTTP MCP transport rather than
`command:` — the store is then owned by a process the stage cannot write to. This
changes `broker_config()` and it is a prerequisite of the inner layer, not a
detail of it: until it is done, a gated stage with a writable store is worse
than a gated stage with no scope at all.

### Publishing without a readable credential

That last denial is not a restriction on publishing. A flow has to be able to
push and open its pull request unattended, so the capability reaches the stage
that needs it — as **environment on the publishing stage only**, the way
provider credentials already do: `ANTHROPIC_AUTH_TOKEN` is resolved from the
environment and never written into the resolved flow.

What the stage does not get is a readable credential *directory*. It cannot
enumerate what else is in there, and it cannot reach a credential for anything
it was not handed. This is narrower than today in the way that matters and it
costs the flow nothing it was doing.

`classic` is one session doing every role, so it holds the publishing
environment for its whole hour rather than for one stage of six. That is a
property of `classic`, not of this feature, and it is one more reason to prefer
a staged flow.

### What a project may add

`repositories` gains an optional mapping form. A bare string keeps working and
means "no extra reads".

```yaml
repositories:
  Example Project: /abs/path/to/repo          # unchanged, no extra reads
  Other Project:
    path: /abs/path/to/other
    reads:                                    # read-only, absolute or ~
      - ~/reference/vendor-api/
```

A project with no entry, or a bare-string entry, gets the default scope — which
is the tightest one. **Absence never widens a scope.** That is deliberate:
Cuzam has already shipped one defect from two places holding the same fact and
drifting, so a missing declaration has to mean "less", never "more".

`reads` is read-only and always. There is no write-outside-the-worktree
declaration, because the thing a flow is for is a branch in a repository.

### Who enforces it

Two layers, and they are not redundant — each covers what the other cannot.

**The outer layer is the operating system.** The launcher generates a
`sandbox-exec` profile and every `claude` process is started under it. This is
the layer that matters, because the inner one cannot see a subprocess: `cat` is
on the read-only allowlist by design, so `cat ~/anything` is invisible to
Claude Code's permission rules and to the broker. Only the kernel is below
`cat`.

Verified before choosing it: `sandbox-exec` `exec`s its target, so the process
tree and argv are unchanged and `ps` shows `claude` as a direct child. This
matters more here than it would elsewhere — streaming a classic run's log
through process substitution was reverted on 2026-09-24 precisely because the
extra process made one run read as two to both liveness implementations. A
wrapper that `exec`s adds no process and breaks nothing.

**The inner layer is Claude Code's own.** Stages pass `--restricted`, which
confines the file tools to the working directories, refuses
`bypassPermissions`, and — the part that is load-bearing for a different
reason — ignores user, project and local settings files. Cuzam supplies its
own via `--settings`.

That last point closes a hole nobody had written down: **today the repository
being worked on decides its own session's permissions.** Claude Code discovers
`.claude/settings.json` from the checkout, so a target repository can ship a
`permissions.allow` list and widen the session Cuzam started. After this
change the scope is Cuzam's, and a committed settings file cannot move it.

**Which cuts both ways, and the spec owes two guarantees because of it.**
Discovered settings can also narrow. This repository's own committed file
denies reads of `~/.ssh`, `~/.aws`, `~/.config/gh` and `.env` files, denies
`Edit(.git/**)`, `sudo` and force-push — and `--restricted` drops all of it. So
Cuzam's `--settings` payload has to deny at least as much as whatever it
displaces, or the inner layer is a net loosening on the one repository we can
actually inspect.

The second is hooks, and here the honest answer is a cost rather than a
guarantee. `--restricted` ignores discovered settings and hooks come from
settings, so after this change a stage has none — Cuzam configures no Claude Code
hooks anywhere, and the hooks a stage has today are the *operator's* machine-local
user settings. Carrying those would mean copying machine-local configuration into
Cuzam's payload, which contradicts computing the scope from Cuzam's configuration
alone and could not be pinned by a test. So the criterion is not "carry the
hooks"; it is that **stages run without discovered hooks, and the OS layer is
what replaces them.**

That is worth stating rather than glossing, because dropping `--bare` was
justified by "hooks are the only hard enforcement boundary a stage has —
permission rules are matched, not enforced". That sentence is still true of
permission rules, and it is the argument for the outer layer: the kernel is an
enforcement boundary in the way a matched rule is not. What is genuinely lost is
whatever the operator's own hooks were doing, and if that matters, the answer is
a hook set Cuzam ships and tests — named work, not an assumption.

**The two layers arrive in that order, and classic keeps its flag set.** The
OS layer goes on all three spawn sites at once, because it is the layer that
closes the hole. `--restricted` and `--settings` go on staged stages only;
`classic`'s argv gains the profile path and nothing else.

Decided rather than deferred by accident. Once the sandbox is on `classic`,
`--restricted` adds a margin there and not much more: confining the file tools
is redundant with the kernel denying the same reads, refusing
`bypassPermissions` is already the S-3 pin with a test asserting no bypass flag
exists in the skills tree, and the settings-provenance fix bites on reads, which
are denied whatever a committed settings file allows. What is left is
allow-listed writes and commands inside the scope — and inside the scope is the
worktree, which `acceptEdits` permits anyway.

Against that margin, `--restricted` on `classic` costs a `--tools` list on the
one argv both liveness implementations read, guarded by a test that pins the
permission mode and the absence of a bypass flag but not the tool set. On
staged stages it is nearly free, because `cuzam_dash_test.py` already pins that
argv down to which commands are absent. So the accepted cost is that `classic`
has no inner layer, and a gap in the generator is unmitigated there.

The follow-up, not this change: pin `classic`'s full flag set in
`run-loop.test.sh`, then add `--restricted --tools …` behind that test.

The broker is not an enforcement layer here. It is not reachable from
`classic` at all, it holds no path policy by design — `approvals.py` says it
"has no policy, no allowlist, and no opinion about which tool calls are safe" —
and a read that goes through `cat` never reaches it. Scoping is not its job and
this feature does not give it one.

### Where the profile lives, and why not in the worktree

`$CUZAM_STATE_HOME/scopes/<task-id>.sb`, written by the launcher, and denied to
the stage that runs under it.

The launcher writes it; `gc` removes it when it reclaims the run's worktree;
nothing else touches it. A resume regenerates it when it is missing and refuses
before re-exec if it cannot — because `classic` re-execs `claude` on resume with
the same path, and a profile that vanished to a state-home reset or a different
`CUZAM_STATE_HOME` would otherwise fail the run mid-flight, after the work. The
launch-time refusal does not cover resume, so resume needs the rule spelled out.

Not in the artifact directory, because the artifact directory is inside the
worktree and the worktree is writable. A stage that could edit its own profile
could widen the scope of the next stage, or of a resume — `classic` re-execs
`claude` on resume with the same profile. This is the same reasoning that
already puts the pid record outside the worktree, "so the policed process
cannot author its own reaping record".

### It fails closed

`cuzam launch` refuses, and refuses early — before the board task is claimed
and before the worktree is cut — when:

- `sandbox-exec` is not usable. Invoked by absolute path, `/usr/bin/sandbox-exec`
  — a security wrapper resolved through `PATH` is not one — with the path
  injectable so the unusable branch is reachable from a test rather than being
  dead code that the test pretends to exercise;
- the profile cannot be generated or fails to parse;
- the project resolves to no computable scope;
- a declared `reads` path is relative, or escapes after expansion.

One exception, named rather than left to collide with the rule: the provider
preflight probe has no worktree, no repository and no project — it runs in a
scratch temporary directory by design. It gets a declared degenerate scope of
that directory plus the runtime set, and it is the cheapest place to prove the
wrapper works at all. It also has to authenticate, which is the first thing the
credential-as-environment principle buys: the probe needs no grant into
`~/.claude` to reach the model, so the degenerate scope stays degenerate. Had the
credential remained a path, the probe would have failed to authenticate, reported
"did not answer", and the fail-closed rule would then have refused every launch
on the machine.

Refusal is a refusal: no run, no worktree, no claim, no half-started flow to
reap. The message names which of the four it was.

There is no per-project opt-out and no `--no-scope` flag. Every other control
here treats silence as deny; a control with a documented way around it is the
control this repo keeps finding defects in.

### Scope does not depend on attendance

Today `unattended: true` strips the gate: no broker, no `--allowedTools`, no
permission prompt tool. Unattended means *strictly fewer* controls, which is
backwards, and it is the direct cause of the surface this spec exists for.

Scope does not join that. It is the same four parts either way, and an
unattended run opens its pull request exactly as an attended one does.
Withholding the publish from unattended runs was considered and rejected: an
unattended flow that cannot finish is not a tighter product, it is a broken
one.

What changes for an unattended run is what the absent gate is worth. The
argument against it was always "nothing gates what this reads". After this
change the kernel does, whether or not anybody is awake — so an unattended run
is bounded by something that never needs an answer from an operator. That is
the part of the inversion worth having, and it is the part that does not cost
anything.

### When a stage hits the boundary

A denied read surfaces as a tool error inside the stage, and the stage's log
keeps it, so a stage that dies on a path the profile forgot is diagnosable
without rerunning it.

No new event kind is promised here, and the reason is worth stating rather than
leaving as an omission. `events.py` is a closed vocabulary — a new kind is a
deliberate change there and in the fleet-view reader — and more awkwardly, the
only process that sees a kernel denial is the one inside the scope. The parent
runner never sees it. So a `scope.denied` event would need the stage to report
its own denial, which is a different mechanism from the one that enforces it,
and it belongs in the change that adds it.

### What this does not fix, said plainly

It does not reduce how often a stage asks. The 57-minute run asked seven times;
six were compound Bash commands that reach the gate by design, and the
seventh was a read outside the worktree. Under this feature that seventh is
denied instead of prompted — faster, and the credentials file is out of reach —
but the other six are unchanged, and a stage that has not been given its
issue's context will still go looking. **Scoping bounds the blast radius. It
does not fix the latency.** Fixing that is `context.md`, which exists, and the
rule stays: a flow is only as good as the issue's context being present.

## Out of scope

- **Network scoping.** A stage that can reach the model API can send it
  anything it has already read. A filesystem boundary that claims to stop
  exfiltration would be claiming something it cannot do. Bounding what can be
  read in the first place is the whole of the control.
- **Replacing the approval gate.** Scoping decides what is *reachable*; the
  gate decides what happens to it. Both, or neither is worth much: a scope with
  no gate permits any command inside it, and a gate with no scope is what
  produced the incident.
- **Enforcement inside Hermes.** Answered 2026-09-24 and not reopened here.
  Hermes has no filesystem scoping either, and that stays Hermes' business.
  The boundary in this spec is one Cuzam owns, generates and tests.
- **The `cuzam chat` process** — as distinct from the assistant's `launch_run`
  tool, which is one of the four surfaces above. It is excluded because it is
  not a flow and needs its own decision, **not** because there is nothing there
  to scope. An earlier draft of this spec claimed it has no file tools; that was
  wrong. `--allowedTools` is a permission allowlist, not the availability list —
  `--tools` is that — so the built-in file tools are present, and the process is
  started with no working directory at all, which makes "the project's settings"
  whatever directory it inherited. On this evidence it is arguably the least
  constrained `claude` process on the machine. Out of scope here, and it should
  not stay out of scope for long.
- **A cross-platform boundary.** `sandbox-exec` is macOS-only and deprecated by
  Apple. macOS is the stated platform baseline, so the outer layer matches the
  product. A second host platform needs a second generator behind the same
  function, and the inner layer already works everywhere.

## Open questions

- [ ] **`--restricted` removes Bash unless `--tools` names it**, so each staged
      spawn has to carry an explicit `--tools` list, and the list has to be
      pinned by the same test that pins the rest of the argv. Settled for
      `classic` (it does not get `--restricted` in this change); still the
      riskiest step for staged stages.
- [ ] **A deny-default profile is real work.** Probed 2026-09-25: an
      allow-default profile with denials enforces immediately, but a
      deny-default profile needs Apple's base profiles and naive attempts abort
      the target before `exec`. Deny-default is the shape this spec describes,
      so the generator's first job is a profile that both denies by default and
      still lets `claude`, `git`, `gh` and `make check` run. If that proves
      unreachable, the fallback is allow-default with an explicit denial set,
      which is weaker in exactly the way this spec argues against — so it comes
      back here as a spec change, not as an implementation shortcut.
- [ ] **The runtime read set is a machine fact, not a config fact.** It has to
      be discovered (the resolved `claude` binary's real path, its node
      runtime, the caches they use) rather than hardcoded, or it breaks on the
      next toolchain move. Where that discovery lives, and whether a wrong
      answer is a launch refusal or a missing path, is undecided.
- [ ] **`classic` gets no `context.md`, which makes this feature a regression
      for it until that changes.** `execute()` raises for `classic` before
      context assembly is reached, and `run-loop.sh` has no equivalent — so the
      most-used path has neither the assembled context nor, afterwards, the
      ability to go and find it. A classic run on an issue whose spec lives in a
      vault note searches for it today; afterwards it is simply denied. Either
      context assembly reaches `classic` first, or scoping lands on staged flows
      first. Sequencing decision, and the one that most affects whether this is
      an improvement on day one.
- [ ] **How the publishing credential resolves is unverified.** The remote is
      HTTPS and no shipped code runs `git push` or `gh pr create` — the model
      does, so `gh` resolves its own token and git resolves a credential helper.
      If either goes through the macOS keychain, the profile needs a
      mach-lookup allowance rather than a path, and an environment token has to
      be able to override the helper. Launch-blocking detail, to be established
      on the machine rather than assumed.
- [ ] **The tight version of this is that the launcher opens the pull request.**
      Then no model process holds a publishing credential at all, in
      environment or on disk. It is a real behavioural change — the `pr` stage
      is a model stage by design and `classic` opens its own PR inside its hour
      — so it is not folded in here. But it makes the credential question
      disappear rather than narrow, and it should be decided rather than
      drifted past.
- [ ] **A shared `.git` is why cross-run isolation needs narrowing at all.**
      The set above is narrow enough to keep runs out of each other's worktree
      metadata and refs, but it is a list of carve-outs in a directory three
      parties share, which is the kind of thing that rots. The structural
      alternative is one git directory per run — a clone rather than a worktree
      — which would make the isolation a property of the layout instead of a
      property of a profile. Bigger change, cheaper invariant; worth pricing
      before the carve-out list grows.
- [ ] **`reads` is per project, not per flow.** A flow that needs a path the
      project does not declare cannot get one. That is intended for now; if it
      turns out flows want different reads inside one project, `flows` is the
      layer that merges by name and would carry it.

## Implementation notes (optional)

Not contractual. Where the boundary would land, given what is there today:

- **One generator.** A single function renders the profile from
  `(worktree, repo, role, project scope)`; nothing else spells a sandbox rule.
  Same discipline as `runs.run_dir()`, which was three places that had drifted.
- **Four spawn sites exist**, and three need the wrapper:
  `cuzam/runner.py:408` (`runner_command`, every staged stage),
  `hermes/skills/loop-runner/scripts/run-loop.sh:280` (classic, which owns the
  S-3 permission pin), and `cuzam/runner.py:658` (the provider preflight probe,
  which already runs in a scratch directory and is the cheapest place to prove
  the wrapper works). The fourth, `cuzam/assistant/loop.py:86`, is out of scope
  above.
- **Classic cannot read the config**, deliberately — it is bash and the
  launcher owns the spawn shape. So the profile path reaches it the way
  everything else does, as argv from `launch.classic_command`, and
  `live_runs_contract_test.py` pins that argv against both liveness matchers.
  Adding an argument to that shape is a change both matchers have to see.
- **`repositories` values become a union.** `config.py:361` validates them,
  `config.py:527` resolves them, `config.py:542` returns the map, and
  `dash/launch.py:956` only sorts the keys. A mapping form is additive;
  `validate_config` is a closed-key validator for `instance` and should be one
  for a scope block too.
- **A new shell test must be listed twice** — `Makefile:25` and
  `scripts/check.sh:21`. `make check` discovers Python tests; `make test` runs
  a named subset and would silently skip a new one.
- **`docs/running-loops.md` § "The context boundary" is stale** and contradicts
  this spec in three places: it claims nothing in a flow can read the issue
  tracker, that the stage prompt carries the issue key and nothing else, and
  that local stages run under `--bare`. `context.py` reaches Linear and the
  vault, `runner.py:273` prepends `context.md` to every stage's inputs, and
  `--bare` is no longer passed anywhere. Correcting it belongs with this change.
