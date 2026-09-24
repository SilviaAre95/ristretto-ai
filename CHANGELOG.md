# Changelog

All notable changes to Cuzam will be documented here. Entries written
before 2026-09-24 name the project Ristretto and the assistant Nemo or
Ris; they are left as written, because what happened, happened under
those names.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and releases use [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`cuzam runs`** — every run with the paths to reach it: worktree, branch,
  the log to tail, the runner's pid, and for a classic loop the pid of the
  Claude process it is waiting on. `cuzam runs <issue>` narrows to one and
  `--json` is the machine-readable form. A path is shown only when there is
  something at the end of it.
- **`cuzam launch --model <tier>`** — `sonnet`, `haiku` or `opus` for a classic
  run, written into the task body so a `cuzam relaunch` runs what the first
  attempt ran instead of silently dropping to the Claude default. A staged flow
  takes its models from its stages and refuses a tier rather than accepting one
  it will not use. The retired `local` tier is accepted and dropped, matching
  `run-loop.sh`, so a task queued before 2026-09-23 can still be relaunched.
- **`cuzam relaunch` refuses when the branch already has a pull request**, and
  names it. The loop opens its PR as its final act, so an open PR means the run
  finished and died before reporting — restarting pays for the whole flow again
  and lets a fresh `finish` stage push over work that is already up. The retired
  `loop-runner` skill made this check before running anything; nothing did after
  the skill went away.
- **A run that died says so.** A run the board still calls `running` with no
  process behind it is reported as `dead` by both the fleet view and the CLI,
  immediately, instead of reading healthy for fifteen minutes and then
  becoming the guess `stalled`. Nothing acts on it: the board is not touched
  and no process is signalled. `cuzam relaunch` stays the deliberate way back.

### Changed

- **One answer to "what is a live run".** There were three and they disagreed,
  and none of them could see a `classic` loop at all — so a healthy
  `run-loop.sh` read as dead from every Python surface. `cuzam/runs.py` now
  answers it for the fleet view, the CLI, the assistant and the relaunch
  guard; `scripts/live-runs.sh` stays a standalone bash implementation on
  purpose, because `install-runtime.sh` consults it while rebuilding the
  Python environment, and a new contract test pins the two against each other
  across all three flows by name.
- Liveness keys on process shape rather than flow name, so `classic`, `full`
  and `short` are two cases instead of three and a fourth flow cannot fall
  outside both implementations unnoticed.
- Both implementations stopped counting a process that merely *mentions* the
  runner — a `python -c` whose source text names the module carries
  `-m cuzam.runner --task-id` on its command line. This is the `pgrep -f`
  failure in another costume; the interpreter must now genuinely have been
  handed the module.
- `cuzam/dash/data.py` moved to `cuzam/runs.py`. The dashboard is one renderer
  over it, `cuzam runs` is another, and nothing in the module assumes a web
  framework — which is what keeps a third surface a rendering job.
- The `.cuzam/runs/<task>` path is built in one place. Three copies had
  drifted, including one in the runner beside its own unused constant.
- `stalled_runs` takes one process snapshot for the whole fleet instead of one
  per task on the board.
- Ten defects found by review of this change, before it merged. The one that
  mattered: an unreadable process table was indistinguishable from an idle
  one, so a single `ps` timeout would have called every claimed run `dead` and
  told the operator to relaunch a working fleet — the failure `dead` exists to
  prevent. Nothing is called dead now without evidence, and every surface says
  when it could not look. Also fixed: the board is read before the process
  table, so a run launched between the two is not reported dead; a staged flow
  started through `run-loop.sh` resolves to its runner rather than to whichever
  of its two processes `ps` listed last; a classic flow given positionally is
  read the way `run-loop.sh` reads it instead of guessed; the shipped
  `cuzam-run-flow` console script counts as a live run in both implementations;
  and the build stamp is taken on first use, so importing the runner no longer
  shells out to `git` twice for something it never reads.
- The installer no longer says the loop flow guard "needs re-approval" after
  an update that changes it. The guard is still armed — Hermes matches an
  approved hook on event and command, never on the script's timestamp — so
  the message now says that and offers the command to clear the notice.

- **Ristretto is now Cuzam, and Nemo/Ris is now Zam.** The system took the
  name `cuzam`, the assistant took `zam`: `ris-*` became `zam-*` (plugins
  `zam-approvals`, `zam-launch`, `zam-chat`; `!zam-approve`), `RIS_*` became
  `ZAM_*`, and `RISTRETTO_*` became `CUZAM_*`. The old `RISTRETTO_*` and
  `RIS_*` names are still read as a fallback for one release, so an
  environment set before the rename keeps working; they are removed in 0.3.0.
  The Python package moved `ristretto/` -> `cuzam/`, the state home
  `~/.ristretto` -> `~/.cuzam`, the user config `~/.config/ristretto` ->
  `~/.config/cuzam`, and run artifacts `.ristretto/` -> `.cuzam/` inside a
  worktree.

  Deliberately **not** renamed: the checkout directory and the GitHub
  repository, which stay `ristretto-ai`; `.cc-verify`, `.cc-dev.yaml` and
  `.cc-deploy.yaml`, which are a contract with wayworks rather than names
  this project owns; and the CHANGELOG entries above.

- **The classic loop is started by the launcher, not by an agent.** `classic`
  was the last flow Hermes still dispatched: a task assigned to `zam-worker`,
  an agent turn reading a skill, and `run-loop.sh` held in that agent's
  foreground. `cuzam launch` spawns it directly now, as `run-loop.sh` rather
  than as the multi-stage runner, which refuses that flow. On 2026-09-10 a
  worker agent abandoned one run and killed two more across four attempts on a
  single issue, reading a silent stage as a hang. Hermes' supervision was never
  the problem — it leases a claim, watches a pid and expects a heartbeat, all
  deterministic. Deterministic work inside an agent turn was, and this was the
  last place that remained true.

  Two things follow. A classic run no longer dies when the gateway restarts,
  because no worker holds it — the cost the comment at the top of
  `run-loop.sh` recorded as accepted is gone rather than mitigated. And nothing
  is retried on crash: that went with the worker, and `cuzam relaunch` is the
  deliberate replacement.

  `loop-runner`'s `SKILL.md` is deleted and the `zam-worker` profile is given no
  skills, so no queued task has a path to an agent. `durable-dev` calls
  `cuzam launch` instead of creating an assigned task. The profile itself stays,
  and so does the loop-completion guard on it: it now guards a path that should
  not be taken rather than one in routine use, which is a reason to keep it
  armed and not a reason to retire it.

### Fixed

- **`cuzam launch --flow classic` reported success and started nothing.** It
  built `-m cuzam.runner --flow classic`, which exits 2 with "classic is
  executed by run-loop.sh, not the multi-stage runner". `Popen` had already
  returned a pid, so the caller was told the run had started while the task sat
  claimed and `running` with nothing running it — and `active_runs` counted it,
  refusing the next launch until the four-hour claim lapsed. `cuzam relaunch` on
  a classic task failed the same way. This was not a corner: `default_flow`
  resolving to `classic` made it the behaviour of every launch that named no
  flow, including the dashboard form and the Slack command.
- **Stop could not see a classic run, and said it had stopped it.**
  `zam-stop.sh` matched two spawn signatures — the worker agent's
  `work kanban task <id>` and the staged `cuzam.runner --task-id <id>`. A
  launcher-spawned classic run is `bash …/run-loop.sh <id> <issue>` and matched
  neither, and until the decoupling it did not have to: killing the worker
  killed `run-loop.sh` as its child. With no worker above it, stop killed
  nothing, passed its own verification — the task was blocked because stop had
  blocked it, and no pid matched a pattern that could not match — and reported
  `stopped`. Verified against a live run before fixing. A third signature
  closes it, and the three are now defined once rather than repeated between
  the kill and the verification. The verification also asks `scripts/live-runs.sh`,
  which `install-hermes.sh` now installs beside it: the signatures cannot audit
  themselves, because "no pid matched" is indistinguishable from "the pattern was
  wrong", so a live process no signature matched reports `NOT STOPPED` and names
  itself rather than passing.
- **A flow removed from `cuzam.yaml` left a relaunch claimed and dead.** The
  flow is resolved before the task is claimed, so an unknown one is refused
  with the board untouched.

### Upgrade notes

This release moves state and links that live outside the checkout, so the
usual `make update` is not enough on its own and will refuse if it runs
first. Once, in this order:

```
git switch main && git pull
make migrate          # moves state, unlinks the old names, relabels launchd
make install-runtime  # rebuilds ~/.cuzam/runtime; the old one is deleted, never moved
make update
```

`make migrate` is idempotent and refuses while a run is live. Three things it
cannot do for you:

- **The microphone grant.** The voice app's bundle id changed
  (`com.ristretto.nemo` -> `com.cuzam.zam`), which revokes its TCC grant.
  macOS asks again on first use; approve it once.
- **The Slack manifest.** `slack/cuzam-slack-manifest.json` is inert until it
  is re-uploaded by hand in the Slack app settings.
- **`SOUL.md`**, if you have edited it. The migration replaces it only when
  your copy still matches the version it was seeded from; otherwise the
  persona keeps introducing itself as Nemo until you port the change. It
  says which it did.

### Added

- `make install-runtime` builds `~/.ristretto/runtime`, a detached checkout of
  `origin/<base>` that dispatched flows run from instead of the working tree.
  The skills are symlinks into the development checkout and the package is an
  editable install, so a flow executed whatever was in that tree when it
  started — uncommitted edits included — and a run could be described only as
  "whatever was there at the time". The launcher stays where you invoked it;
  what gets pinned is the hour of unattended work. Updating is deliberate
  rather than automatic, because a runtime that fast-forwarded on its own
  would run code you had not chosen, just from a different moment.

  With no runtime installed a launch still starts, runs from the development
  checkout, and says so in the launch outcome — visibly unpinned rather than
  silently so.

  The pin holds against both ways it can be undone: flows run with `-P` so the
  worktree is not placed on `sys.path` (a worktree of *this* repository
  contains a `ristretto/` package, so the pin was defeated for the repository
  where it matters most), and `PYTHONPATH`/`PYTHONHOME`/`VIRTUAL_ENV` are
  stripped, since `-P` does not cover them and `scripts/check.sh` and
  `run-loop.sh` both export `PYTHONPATH`. The installer verifies the runtime
  imports `ristretto` *from the runtime* rather than merely importing it at
  all, refuses while a flow is running, and requires Python 3.11 like the rest
  of the project.

### Changed

- Local stages keep their hooks. A provider with a `base_url` gets
  `--strict-mcp-config` instead of `--bare`. The XARI-119 hang was one network
  call — MCP discovery against `api.anthropic.com` with no timeout — and
  `--strict-mcp-config` is the fix for exactly that; `--bare` also worked but
  additionally disabled hooks, plugins, keychain reads and CLAUDE.md. Hooks are
  the only hard enforcement a stage has, so under `--bare` tier1's `build` and
  `finish` ran with none, and `finish` is the stage that pushes: the least
  supervised stage had the most reach, and every model stage in tier3 was in
  the same position. Measured 2026-09-20 against qwen3.6:27b — answered in 94s
  under load, rather than never. The approval broker still loads, verified
  against a live run.

- Mutating stages are told to create and change files with the Write and Edit
  tools rather than shell redirection, heredocs or scripts. A build stage
  raised **sixteen** approvals appending one route to one file, escalating
  `cat` → `sed`/`head` → a Node script as each got gated, and destroyed 289
  lines with `head -n -1` — a GNU option macOS rejects. Write and Edit are
  already permitted for in-worktree files and never prompt, and they match on
  content rather than line position, so a wrong assumption fails instead of
  silently deleting.

- The docs say where Hermes Agent comes from. It is a hard requirement with no
  URL, package name or version anywhere in the repository, so the one step a
  stranger cannot skip was the one step unwritten: `hermes-agent` by Nous
  Research, MIT, on PyPI and GitHub, developed against 0.18.x. Recorded in
  `docs/getting-started.md`, in the README, and in the message
  `install-hermes.sh` prints when the binary is missing — the place it is
  actually hit. Two stale rows in the same requirements table went with it:
  Claude Code is no longer optional, since every flow runs on it, and the
  default flow is `full`, not `classic`.

### Fixed

- `make update` no longer runs over work in flight. It restarted the gateway
  unconditionally, and `hermes gateway restart` is a kill: Hermes resolves its
  drain budget to `0` by default and documents why — a window large enough to
  save a long agent turn would have to outlast an unbounded task. So
  `agent.restart_drain_timeout` exists but buys seconds against runs measured
  in hours, and the default stands. The restart is also not the only hazard;
  `install-hermes.sh` repoints the `loop-runner` link and a runtime rebuild
  swaps code a staged flow is executing out of, so the refusal covers the
  whole update rather than the restart alone.

  `scripts/live-runs.sh` answers "is anything live" from the operating system
  rather than the board, because a run whose process died stays `running` and
  claimed and reads as healthy from every surface — so a stalled run does not
  block an update. It matches both shapes, which `install-runtime.sh`'s
  existing guard did not: that one matched only `ristretto.runner`, and the
  classic loop is pinned the same way, so a live `run-loop.sh` walked straight
  through it.

- A stage killed by a signal keeps what it wrote. XARI-118 covered the
  runner's own deadline and a later change covered the runner being signalled,
  but neither fired when the *stage child* was killed and the runner lived to
  process an ordinary non-zero exit — which is precisely what the Stop button
  produces. Seven files sat uncommitted in a worktree `ristretto gc` would have
  reclaimed. Found by pressing Stop.

### Fixed

- `ristretto preflight` says what it did not check. The fast path verifies the
  loop's own files are committed and printed only `OK` lines, which reads as
  "this repo can run a loop" — the stronger claim the module's own docstring
  calls the only question that matters. crema-connect reported `OK` on
  2026-09-18 with a verify gate that had been red for weeks (a stale install,
  not a code error), so a run there would have executed every stage and died
  at `verify` on a breakage that predated it. A passing fast check now ends
  with an `UNKNOWN` line naming `--deep`. `UNKNOWN` is not a failure and does
  not block a launch: it is an unanswered question, not a broken repo.

  A launch reports the same unanswered question in its confirmation, since the
  incident it guards against was a launch rather than a command-line check, and
  `preflight.passed` events carry an `unchecked` field when the gate was not
  run — an unqualified pass is a durable record claiming more than was
  established.

### Added

- A run records which code ran it. `flow.json` gains a `runner` block with the
  version, commit, branch and whether the tree was clean — beside the
  `verify_sha256` and `stage_timeout` it already pins for the same reason.
  The skills are symlinks into the working checkout and the package is an
  editable install, so the runtime *is* the tree, including uncommitted edits
  and whichever branch is out; a run could previously be described only as
  "whatever was there at the time", which twice required a `git checkout main`
  before a dispatch for its result to mean anything. This records rather than
  fixes, deliberately: the first reading says whether promoting a built
  artifact is worth the velocity it would cost.

### Fixed

- `ristretto.__version__` reads `VERSION` instead of restating it. The literal
  said `0.1.0` while `VERSION` said `0.2.0` and `v0.2.0` was tagged, so the one
  place a program could ask was the one place that was wrong.

### Added

- Ristretto loads the secrets it declares. Real credentials are env-only by
  design — `config.py` refuses a provider `auth_token` that is not the
  non-secret placeholder — but nothing populated those variables. It worked
  for one launch path and not the other: Nemo and the gateway are hermes
  processes and already hold hermes' environment, while a `ristretto launch`
  from a shell holds nothing, and the two are indistinguishable afterwards
  because a key that is present but unreadable degrades exactly like a key
  that is absent. `~/.config/ristretto/env` is read first, then
  `~/.hermes/.env`; anything already exported wins over both.

  Only the names this installation declares are loaded — the `*_env` values
  from the instance and providers, plus `LINEAR_API_KEY`. The files hold other
  projects' credentials, and `start_flow` hands its whole environment to a
  process running generated code, so loading one wholesale would put Slack and
  browser tokens in front of a model that has no use for them.

- The flow is told what it was asked to do. Before any stage runs, Ristretto
  assembles `context.md` into the run's artifact directory from the issue body
  and any vault notes matching the issue key, and lists it as an input to every
  stage. The stage prompt carried `Issue key: XARI-123` and nothing else, so a
  flow began by not knowing the task: where the issue was about code the plan
  stage reconstructed it, and where it was about product the build stage went
  hunting — seven permission prompts and 57 of one run's 60 minutes, ending at
  an attempt to read a credentials file. Those searches were this project's own
  premise being carried out by hand, through a gate, because nothing did it
  first.

  Every source degrades to absent, and a missing one is stated in the artifact
  rather than left as a silent gap — a stage that can see "the tracker was not
  reachable" says so in its plan instead of going looking. The vault half works
  today; the issue half activates when `LINEAR_API_KEY` is set, there being no
  Linear credential or client anywhere in the project until now.

- A flow makes git ignore its own artifact directory before writing anything
  into it, in that checkout only. `preserve_work` already excluded it, but the
  `pr` stage is a model running `git add` and four of six configured
  repositories do not ignore `.ristretto` (XARI-130) — untidy while the
  directory held logs, and not untidy at all once it holds excerpts of the
  operator's notes. The flow refuses to start if it cannot.

### Fixed

- Approval requests larger than 4000 characters are readable again. The stored
  tool input was clipped as serialised JSON, which cut it mid-string so it no
  longer parsed; the card then rendered a tool name and nothing else. Every
  approval a local coder raised on 2026-09-11 was unreadable this way — five in
  a row — because the model writes files with long heredocs, which made the
  gate unusable in the flow it matters most for. Values are clipped instead, so
  the document always parses, and a record that still cannot be read now says
  so rather than looking empty.
- A stage that stops because it exhausted its approval-waiting credit no longer
  commits under "stage timed out after 3600s", which reads in git log as having
  run out of working time.
- `.gitignore` ignores a `.venv` symlink, not only a `.venv` directory. Warming
  a worktree by symlinking the virtualenv left it untracked and eligible to be
  committed by `preserve_work`.

- `ristretto stop` actually stops a directly-launched run. It killed by the
  Hermes worker's spawn signature, which no longer exists, and then verified
  by asking "is the task blocked?" (it blocked it itself) and "are there
  worker pids?" (there never were) — so it reported success while the flow
  carried on to the stage that pushes.
- A failed launch releases its claim instead of leaving the board saying
  "running" with nothing running. One failed launch used to refuse every later
  launch until the claim lapsed.
- An approval too large to store now describes itself instead of rendering as
  a bare tool name — the blank cheque, reintroduced by the fix's own fallback.

### Added

- `ristretto relaunch [task-id | issue-key]` restarts a run whose process died,
  in the worktree and branch it already has. Removing the worker also removed
  Hermes' retry-on-crash, and relaunch was otherwise impossible: the
  idempotency key is scoped to a day, and a dead-but-claimed task counts as
  active. With no argument it restarts the only stalled run, names them if
  there are several, and distinguishes "nothing to restart" from "it is still
  running". It resumes the flow at `plan`; anything `preserve_work` committed
  is already on the branch.

### Changed

- `ristretto launch` runs the flow itself instead of dispatching a worker
  agent. It claims the board task, cuts the worktree, and starts the runner as
  a detached process; the board keeps the card and the lease, and the runner
  already heartbeats and reports its own outcome. Every Hermes task is assigned
  to an agent profile, so dispatching meant a language model was the thing
  running a script and waiting for it — and on 2026-09-10 that model abandoned
  one healthy run and killed two more across four attempts, reading a silent
  stage as a hang. Hermes' supervision was never at fault; it leases, watches a
  pid, and expects a heartbeat. The mistake was putting deterministic work
  inside an agent turn.

  The board task is created **unassigned**, which is what keeps a worker away:
  `_cmd_dispatch` only considers a task where `status == "ready" and
  task.assignee`. A claim alone would not hold — `hermes kanban heartbeat`
  renews the worker, never the claim (Hermes documents the trap itself), so on
  a run longer than the TTL the claim lapses, the task returns to ready, and a
  dispatcher tick would put a second runner in the live worktree. Setting
  `kanban.default_assignee` would silently undo this.

  **Upgrade note:** a launch that cannot start now reports failure instead of
  "queued". Nothing will pick the task up later, because claiming it is what
  keeps the dispatcher away.

- A running flow now prints what it is doing every 30 seconds, naming the
  stage, how long it has been going, and how much of that was spent waiting on
  a person. Stages were silent for tens of minutes — the model's output goes
  to an artifact, not the terminal — and the supervising worker agent read
  that as a hang and killed three healthy runs in one afternoon.
- A stage killed by a signal now commits what it wrote, the same way a
  timed-out one has since 0.2.0. The recovery only ever fired on the runner's
  own deadline, so an external kill discarded finished work — 148 lines in the
  case that prompted this, saved only by committing them by hand.
- `ristretto launch` creates the run's branch at `origin/<base>` before
  dispatching. Hermes otherwise cuts the worktree from whatever the repository
  checkout has selected, so a developer with a feature branch checked out
  silently based the run — and its pull request — on unrelated work.

- A stage's clock no longer runs while it waits for a person to answer an
  approval. The budget measures working time: blocked intervals are read back
  from the approvals store and added to the deadline instead of charged
  against it. Attended runs were failing *because* they asked permission —
  one build stage spent 3437 of its 3600 seconds blocked and got 163 seconds
  of work — which defeats the point of approving from a phone. Overlapping
  requests count once, and the forgiveness is capped at two hours so an
  abandoned run still releases its worktree.
- A provider fallback chain that loops back on itself is now rejected at config
  validation. `run_stage` retries by recursing into the fallback provider, so
  an `a -> b -> a` config recursed once per attempt with nothing to stop it,
  and every hop is a real model run holding a real worktree.

### Changed

- Approval cards now stay actionable for 30 minutes instead of 5. The Hermes
  baseline (`hermes/config.yaml`) gained an `approvals.gateway_timeout` of
  1800s; Hermes' own default of 300s expired while the operator was away from
  the desk, and an expired card in Slack stays clickable while no longer
  reaching the agent.

### Upgrade notes

- `hermes/config.yaml` gained an `approvals` block. Existing installs: run
  `bash scripts/template-drift.sh`, port the block into
  `~/.hermes/config.yaml`, then acknowledge with `--ack`. Restart the gateway
  for it to take effect.

## [0.2.0] - 2026-07-27

Reliability release: verified-state reporting, queued-task lane discipline,
and a real user update path.

### Added

- One-command user update path: `make update` pulls the release
  (`--ff-only`), re-runs the idempotent installers to refresh symlinked
  assets, reports template drift, and restarts the gateway. The installer
  now records which template version seeded the user-owned persona/config
  (`~/.hermes/.template-seeds`); `scripts/template-drift.sh` reports — and
  never merges — upstream template changes, acknowledged with `--ack`.
- Release methodology docs: "Upgrade notes" changelog convention and user
  update path in `docs/releases.md` and `docs/getting-started.md`; placement
  rule in `CONTRIBUTING.md` (behavioral guardrails live in skills, which
  propagate on update; voice/personal context lives in the copy-once
  persona/config seeds).

### Upgrade notes

- The persona template gained verified-state reporting and queued-task
  rules this cycle (see *Changed*). Existing installs: run
  `bash scripts/template-drift.sh`, review the printed diff against
  `~/.hermes/SOUL.md`, port what applies, then acknowledge with `--ack`.

### Changed

- Verified-state reporting: the persona and worker skill now require every
  status claim (edited, committed, pushed, PR open, merged, deployed) to be
  derived from a fresh command check at message time, with file paths cited
  as written — a PR the assistant opened is reported as "open, ready for
  review", never "merged" (the user merges).
- Lane discipline for queued work: the producer skill now forbids dequeuing
  a ready task to implement it inline. A request to hurry a queued task
  means report state and expected worker pickup; `hermes kanban remove` is
  reserved for explicit user-requested cancellation.

## [0.1.0] - 2026-07-21

Initial open-source release.

### Security

- Pin `.cc-verify` before model stages and refuse modified verification gates.
- Block pushes of inherited private history and broaden publication/secret scans.
- Validate worker identifiers and require exact runner executable identities.

### Added

- Open-source readiness audit and publication gate.
- Reproducible local development commands.
- GitHub CI and tagged-release workflows.
- Validated public provider and custom coding-flow configuration.
- `classic`, `balanced`, `quality`, and `local` coding-flow presets.
- Multi-stage Claude Code/Codex runner with artifact handoffs and deterministic verification.
- Ristretto CLI, provider doctor, and safe first-stage installer/uninstaller.
- User-owned instance and repository configuration with environment overrides.
- Idempotent Hermes asset/worker/cron installer with explicit service opt-in.
- Private/public repository split and history-free public snapshot exporter.
- Getting-started guide and illustrated README.
