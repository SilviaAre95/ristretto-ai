# Running a loop

How to run a multi-stage coding flow, what to expect while it runs, and what
to do when it goes wrong. Everything here has been run, not inferred — where
something is known to be broken it says so rather than describing the intent.

## Two ways to run, and why you probably want the second one

**Dispatched.** `cuzam launch <project> <issue>` creates a Hermes task,
claims it, cuts a worktree at `origin/<base>`, and starts the flow as a
detached process. No worker agent is involved: the board keeps the card and
the lease, and the flow reports its own outcome.

It used to hand the task to an agent profile, which meant a language model was
the thing running a script and waiting for it. That needs no judgement, and
the judgement is what failed — on 2026-09-10 a worker abandoned one run and
killed two more across four attempts on a single issue, reading a silent stage
as a hang. Hermes' own supervision was never the problem; it leases a claim,
watches a pid and expects a heartbeat, all deterministic. The mistake was
putting deterministic work inside an agent turn.

`classic` was the last flow that still worked that way, and it stopped on
2026-09-24. It is spawned here too, as `run-loop.sh` rather than as the
multi-stage runner — which refuses it — with `--model <tier>` for the one
flow that takes one. Two things follow. A classic run no longer dies when the
gateway restarts, because no worker holds it. And nothing is retried on crash:
that went with the worker, and `cuzam relaunch` is the deliberate replacement.

**Standalone.** You run the flow yourself, in a directory you chose:

```bash
.venv/bin/python -m cuzam.runner \
  --task-id t_anything --issue XARI-123 --flow full
```

For `classic` the standalone form is the script, since the staged runner
refuses that flow:

```bash
bash ~/.hermes/skills/software-development/loop-runner/scripts/run-loop.sh \
  t_anything XARI-123 --flow classic
```

Run it from the worktree you want it to work in. It is no longer an agent-facing
skill — the directory is still linked there because `zam-stop.sh` finds
`reap.sh` through that path, but its `SKILL.md` is gone and no agent is given
it.

`--task-id` is only a label. It names the artifact directory and keys your
approvals; **it does not have to exist on any board.** Nothing about the flow
needs Hermes.

Standalone is worth knowing about because the flow runner has always been the
reliable half — it produced the work in kaffecard #24 and #25 — while every
failure on 2026-09-10 came from the agent supervising it, which read a silent
stage as a hang and killed three healthy runs. That layer is gone from the
dispatched path too as of 2026-09-24, so the difference is now smaller than it
was: standalone means the run has no board entry, no claim and no artifact
directory you did not choose, and nothing watching it but you.

It also works in repositories that are not configured projects, because there
is no project name to resolve — including this one.

## Which copy of Cuzam runs

A dispatched flow runs from `~/.cuzam/runtime` — a detached checkout of
`origin/<base>` that nobody edits — not from your working tree. Build or
update it deliberately:

```bash
make install-runtime
```

This exists because the skills are symlinks into the working checkout and the
package is an editable install, so a flow used to execute whatever was in that
tree at the moment it started: uncommitted edits, whichever branch was out. A
run could be described only as "whatever was there at the time", and twice an
experiment had to be preceded by `git checkout main` for its result to mean
anything.

Updating is a decision, not a background fast-forward — a runtime that moved
on its own would reintroduce the same problem in a slower form. `flow.json`
and the `control.launch` event both record which commit was chosen, and whether
that checkout was clean.

With no runtime installed a launch still works, runs from the development
checkout, and says so. Standalone runs (`python -m cuzam.runner`) are
unaffected: you chose the interpreter, so you already know which copy it is.

## The flows

A flow is how much scrutiny a change gets. All coding runs on Claude.

| flow | plan | build | review | repair | finish |
|---|---|---|---|---|---|
| full | opus | sonnet | opus | sonnet | haiku |
| short | opus | sonnet | — | — | haiku |

Both have a `verify` stage before `finish`, which runs the repository's
`.cc-verify` and nothing else. In `full` it sits between `repair` and
`finish`; in `short` it is the only thing between the build and the branch,
which is why `full` is the default and `short` is something you ask for.

`short` plans on Opus rather than Sonnet because it has no review stage: the
plan is the only judgement in the flow, and plan is the cheapest stage to
spend a stronger model on — it reads little and runs once.

There used to be a `tier0`–`tier3` ladder here, graded by how much Claude a
run used, with the build on a locally served coder. That was retired on
2026-09-23 after every local build died in the build stage.

`--dry-run` prints the exact command each stage will execute without spending
anything. Do this before trusting a flow you have not run.

## What a stage may do

Read-only stages (`plan`, `review`) run under `--permission-mode plan` with no
permission broker attached. **They cannot ask you for anything and cannot
write.** Only `build`, `repair` and `finish` are gated, and in-project edits are
covered by `acceptEdits` without consulting the gate at all — so a well-scoped
issue often raises zero approvals. XARI-129 raised none.

Answering, from anywhere:

```bash
cuzam approvals pending
cuzam approvals allow <id>     # or deny <id>
```

An unanswered request expires after 30 minutes and is treated as a deny.
Waiting is not charged against the stage budget — the clock stops while a
request is outstanding.

## The context boundary

**On a staged flow, no stage goes to your issue tracker itself — Cuzam goes,
before any model starts.** The multi-stage runner assembles `context.md` into
the run's artifact directory and prepends it to every stage's inputs: the issue
title and body when a tracker credential is configured, and up to three matching
vault notes, clipped. It carries a line telling the stage to treat all of it as
data and never as instructions. When the tracker is unreachable the file says so
explicitly, and says not to go looking for the issue elsewhere on the machine.

**`classic` gets none of this.** The runner raises for `classic` before context
assembly is reached, and `run-loop.sh` has no equivalent — so the most-used flow
still works from the issue key and the repository alone. That is the gap behind
the incident below, and it is why `filesystem-scoping` names context assembly
for `classic` as a sequencing decision rather than an afterthought: denying the
search without supplying the context would make `classic` worse, not safer.

This is the shape the boundary should have. The reading that a flow legitimately
needs from outside the repository is done by deterministic code with a fixed
list of sources, before any model starts, and arrives as a file inside the
worktree — rather than by a model searching a home directory one permission
prompt at a time. `filesystem-scoping` is the other half of that: it denies the
search.

What a staged stage still cannot do is reach the tracker live. It has
`context.md` and the repository, and nothing else, so the rule below is
unchanged — and holds more strongly for `classic`, which has only the
repository.

Two earlier claims here were wrong and are corrected above. The stage prompt no
longer carries `Issue key: <KEY>` and nothing else, and `--bare` is no longer
passed anywhere — `--strict-mcp-config` replaced it, which matters because
hooks are the only hard enforcement boundary a stage has, and under `--bare`
the stage that pushes was running with them off.

So the rule is: **a flow is only as good as the issue's context being present
in the repository.** XARI-123 was about `preserve_work`, so the code was the
spec and the plan came out right. XARI-31 was a product spec living in a vault
note, so the build stage spent 57 minutes of its hour at permission prompts
searching the operator's notes, ending at an attempt to read a credentials
file. If a run asks a lot of questions, suspect missing context, not the gate.

One correction to the "read-only stages cannot write" rule above: a `plan`
stage has been observed writing its plan to `~/.claude/plans/` — outside the
worktree. It cannot write to the repository, which is what matters here, but
it is not inert.

## While it runs

A stage prints one line when it starts and the model's own output goes to an
artifact file rather than the terminal, so the flow would otherwise be silent
for tens of minutes. It therefore reports itself every 30 seconds:

```
flow: build running 4m12s
flow: build running 7m30s — 3m18s of it waiting on you
```

The second form means the flow is stopped at a permission prompt. That is a
normal state and the time is not being charged to the budget. **If the ticks
are arriving, the flow is alive** — that is the liveness signal, not the
absence of other output.

Artifacts land in `.cuzam/runs/<task-id>/`: `plan.md`, `build.md`,
`review.md`, and a `.log` per stage. Each stage's output is the next stage's
input. When a run produces something strange, read `plan.md` first — a bad plan
looks exactly like a model failure three stages later.

`cuzam runs` prints every run with the paths to reach it — worktree, branch,
the log to tail, the runner's pid and, for a classic loop, the pid of the
Claude process it is waiting on. A launched classic run has a `flow.out` like
any other, filled with the harness's own output as it goes and Claude's when
the run ends; a hand-run one keeps Claude's output in a temporary file and
offers no log. It shows the same facts as the fleet view and
reads from the same module; the command exists so the paths can be pasted
straight into a terminal. `cuzam runs <issue>` narrows to one,
`cuzam runs --json` is the machine-readable form.

A path appears only when there is something at the end of it: a worktree
`cuzam gc` has reclaimed is still named, marked as gone, and a log is offered
only when the file is really there.

## When it goes wrong

**A dead run says so.** `cuzam runs` and the fleet view both report a run the
board still calls `running` with no process behind it as `dead` — a fact from
the process table, unlike `stalled`, which is a guess from silence. Neither
surface does anything about it: the board is not touched and no process is
signalled, because on 2026-09-10 a surface that could not tell alive from dead
restarted three healthy runs. `cuzam relaunch <issue>` is the deliberate way
back, and it starts again from `plan`.

**Interrupting is safe.** Ctrl-C commits whatever a mutating stage has written
as a `wip(<stage>)` commit on the run's branch, with a `Cuzam-Preserved`
trailer, rather than leaving it to be reclaimed with the worktree. The same
happens if the stage hits its deadline.

**A timeout says which kind it was.** `timed out after 3600s of working time
(40m waiting on approvals was not charged)` means raise the budget;
`timed out: 120m spent waiting on approvals reached the 120m the stage clock
will hold for` means answer faster. They need opposite responses, which is why
the message distinguishes them.

**A cold worktree cannot run the verify gate.** A fresh worktree has no
`node_modules`, no `.venv`, no generated client. `.cc-verify` will fail on
setup rather than on the code. Warm the worktree first, or declare a larger
`stage_timeout` in the repository's `.cc-dev.yaml` so setup does not eat the
budget.

**Branch from `origin/<base>` after fetching.** `cuzam launch` now pins
this itself, but if you create a worktree by hand, `git worktree add` cuts from
whatever the checkout has selected. A repository parked on a feature branch
silently bases the run on unrelated work, and the resulting pull request looks
legitimate.

## Known rough edges

- On the board, `blocked` means "failed and gave up", not "waiting for your
  approval", and `unblock` restarts the run from the beginning — it has
  discarded completed stage work.
- There is no filesystem scoping yet. A stage can read anything the operator
  can, and on `classic` there is no broker to ask, so nothing gates it. Spec'd
  as `filesystem-scoping`; until it ships, treat an unattended run as having
  your home directory's read access.
