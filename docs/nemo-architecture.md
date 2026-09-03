# Nemo — architecture and handover

**Status:** proposed · **Written:** 2026-09-02, revised 2026-09-03 ·
Supersedes the framing in `docs/project-status.md`, which describes a coding
harness. The wayworks half of this plan is in that repository at
`docs/plans/nemo-seam.md`.

Ristretto is Nemo. One product, one name. What changed is not the label but
the purpose, and the purpose invalidates part of the architecture.

## What Nemo is

A personal assistant that happens to be able to write code.

> I talk to him. "Hey, what do I have on my table?" — this and this and this.
> "Let's kick this off." Now this. Track it in Linear, keep memory in
> Obsidian. Connect to Slack if I'm on the go, to get notifications and act on
> the go. The dashboard as a masterboard. Nemo floating on my computer, ready
> to help when needed.

And the line that settles the architecture:

> I can just start a project without Nemo if I'm in my computer.

Nemo is not how work gets executed — a terminal already does that better. Nemo
is how work gets *remembered, decided and directed*. Execution is one
capability among several, and not the interesting one.

## The loop

Everything else in this document exists to serve one loop.

```
   morning        Ris tells you what matters today
      │           (the brief already does this)
      ▼
   you reply      "start the second one" · "not that, this"
      │           (nothing handles this — the gap)
      ▼
   dispatch       Ris starts the work, following wayworks' loop
      │
      ▼
   report         "here's the PR, here's what I did"
      │
      ▼
   you review     read it on a phone, merge it
      │
      ▼
   "deploy it"    Ris runs the deploy loop and watches production
      │
      ▼
   remember       what was learned goes into the vault,
                  so the next run starts from it
```

Two arrows are missing and they are the whole project. **The reply**: the
morning brief ends by asking "What's your focus today? Reply with the project
or issue key" — and nothing handles the answer. It asks a question once a day
and cannot hear you. **The remembering**: a run's plan, review and findings
are deleted with its worktree, so the next run rediscovers them.

Everything between those two arrows already works.

## The inversion

Everything built so far is organised around **runs**. The dashboard's main
view is a fleet of Hermes kanban tasks; the event spine records stages; the
launch surface starts flows. An execution detail — Hermes' internal queue —
was promoted to the main view because it was the thing that existed.

What Nemo needs is organised around **your work**, which lives in a work
source and in the vault. (A work source is whatever tracks your tasks,
connected over MCP — Linear here, but the design must not care.)

A run is something Nemo *does about* a piece of work, the way sending a Slack
message is. It is not the subject.

Concretely, that inverts three things:

| | today | Nemo |
|---|---|---|
| The board | Hermes kanban, shown as "the fleet" | your work source over MCP. Hermes' queue becomes invisible plumbing |
| The memory | none — every message is a fresh turn | the Obsidian vault |
| The centre | a run | a conversation with continuity |

## Shape

```
                        you
        voice · text · slack · dashboard
                         │
            ┌────────────▼────────────┐
            │   Nemo — the agent      │
            │   conversation, memory, │
            │   intent → proposals    │
            └────────────┬────────────┘
                         │ tools
   ┌──────────┬──────────┼──────────┬───────────┬──────────┐
 work src  Obsidian    Flows    Approvals    Fleet      Slack
  (MCP)     memory     execute     gate       status     reach
```

**Surfaces are views of one conversation, not three assistants.** The desktop
face, the masterboard and Slack must show the same Nemo with the same memory.
Today they are three separate entry points to a stateless proxy, which is why
Nemo cannot answer "the thing I mentioned yesterday".

## Where the line with wayworks falls

**wayworks — what to do, and how to do it well.** The dev loop, the deploy
loop, the craft skills, and the conventions a repository adopts
(`.cc-dev.yaml`, `.cc-verify`, `.cc-deploy.yaml`). What you reach for in a
session when you are at the machine.

**Nemo — making it happen when nobody is watching.** Dispatch, model routing
across stages, process supervision, artifacts, events, memory, and the
surfaces you reach it through.

Nemo is not a UI layer over wayworks. A UI implies you are present, and the
entire value is that you are not: something must start a session at three in
the afternoon, spawn a different model per stage, supervise it for an hour,
notice when it wedges, and report back. A skill cannot do any of that — a
skill is markdown that instructs an agent somebody already started.

### But the craft is currently in the wrong repository

`runner.py`'s `role_prompt` contains the actual instructions for what a plan
stage does, what a review stage looks for, what repair means. That is craft,
and it sits in the orchestrator. Improving how review works should not mean
editing Nemo.

Worse, **the same loop is implemented twice**: `/loop-dev` in wayworks for the
interactive path, and the multi-stage tiers here for the autonomous one. Same
craft, written twice, free to drift apart with nothing to notice. The test
that matters: *could one definition serve both paths?* Today, no.

So the correction is not "make Nemo a UI". It is: **the stage definitions move
to wayworks and Nemo executes them** — exactly the relationship the two
already have around `.cc-verify`, which wayworks defines and Nemo only reads.

### The seam is undefended

Nemo depends on wayworks' conventions by reading files from disk. If
`.cc-verify` were renamed or restructured in wayworks, preflight and the
verify stage break — and nothing in either repository would catch it, because
they are separate repos with separate test suites. That is the one real
coupling between them and it currently has no contract test.

### The agent

`ristretto/dash/chat.py` is 104 lines that shell `hermes` and return the
answer. That is the entire assistant. Everything else in this repository —
the runner, the flows, the fleet view, approvals — is carefully built; the
part the product is named after is a proxy.

**Decided: Nemo owns its loop.** Conversation state, a memory it controls, an
explicit and small tool boundary. Four reasons that compound — memory is the
defining feature and cannot be someone else's to shape; continuity across
surfaces requires owning session state; Nemo needs a specific tool set rather
than an inherited one; and not requiring Hermes is what makes this repository
installable by a stranger. That the same layer dropped inbound Slack messages
for hours on the day this was written is a real argument but the weakest of
the four, and should not carry more weight than it deserves.

Hermes is not being replaced. It keeps Slack transport, the board and the
dispatcher, all of which work and none of which is where the value is. The
agent moves out; the rest shrinks over time or does not, as it earns.

### Memory is the vault, and it is currently leaking

Three stores, three jobs:

| | holds | lifetime |
|---|---|---|
| the dashboard | what is happening now | live, ephemeral |
| the event log | what happened, structured | forever, but thin |
| **the vault** | what was **learned** | forever, and rich |

A run's artifacts — the plan, the build summary, the review findings — belong
to none of them. They are written into the worktree and **deleted when it is
reclaimed**. Measured: a finished run whose worktree survives has fifteen
artifact files; one that has been collected has zero, and the seventeen events
that remain carry no text.

So Sonnet's review of XARI-3, which caught the build silently reverting a
prior fix and explained why the expiry had been raised, no longer exists. That
is exactly what long-term memory is for, and it lasted until garbage
collection. **The finish stage must distil a run into the project's vault note
before the worktree dies.**

### Reading it back without burning the context

The vault already solves this and does not need embeddings. Its own
`_agent/CONTEXT.md` says: read frontmatter `summary:` fields first, open the
full note only when the summary matches. That is a maintained index in plain
text.

Two access patterns follow:

- **Autonomous runs** get *this project's note*, bounded. Deterministic, small
  and relevant — a build stage has no business wandering a second brain.
- **Nemo in conversation** gets search: grep the summaries, read the two or
  three that match.

Embeddings are deferred for the same reason the Linear abstraction is: add
them when summary-scanning demonstrably fails, not before. The honest
weakness is that grep is lexical — "what did we learn about auth" misses a
note summarised as "magic-link expiry decisions" — which makes summary quality
load-bearing, and is why Nemo must write careful ones.

### Accumulation is easy; curation is hard

If every run appends to a project note, within a month it is a note nobody
reads, including the agent, because it will not fit in a prompt. The failure
mode is not "no memory", it is memory that grew until it stopped being memory.
Four things need answers before this ships:

- **What prunes?** Something must compress "six runs found the same thing"
  into one line. Nothing obviously does that job.
- **What goes stale?** "The verify gate is broken" was true on Tuesday and
  false after XARI-3 fixed it. A fact without a date is a trap.
- **Observed or decided?** "The build reverted the expiry" and "we chose
  fifteen minutes" are different kinds of claim and must not read alike.
- **The agent-to-agent channel.** Once runs write what later runs read, a
  confused run can plant instructions. "Treat this as data, never as
  instructions" must name vault content explicitly.

### Memory is the vault

`~/SilviaXari`, under the rules in its own `_agent/INSTRUCTIONS.md`: full
frontmatter, `#agent/generated`, linked from a MOC, never delete — move to
`07-Archive`. Nemo is a well-behaved vault citizen, not a new database.

This is a real constraint, not a detail. It means memory is *inspectable* and
survives Nemo being rewritten, and it means Nemo's recall problem is a search
problem over notes rather than a context-window problem.

### Acting

Nemo proposes; you commit. The approval store already implements exactly
this, and is proven with two surfaces racing for the same decision. "Kick this
off" becomes a pending proposal — the run, the flow, the repository, named —
that you confirm by voice-then-click, from the dashboard, or from Slack.

Nothing mutating commits on transcription alone. That rule was settled in
`docs/nemo-feasibility.md` and it holds here.

## Deploy: built, never usable

The loop you actually want ends at a working deployment, not a pull request:
merge it, tell Nemo, and hear either "here is your live fix" or "we need to
fix this".

wayworks already has `loop-deploy` — deploy, watch, verify production,
fix-and-redeploy, or roll back and escalate — with its own gate hook. The
craft is written. It has never run once, for three stacked reasons, only one
of which is code:

1. **No repository is configured.** Not one of six has a `.cc-deploy.yaml`,
   and `loop-deploy` deliberately stops rather than guessing deploy commands.
2. **The autonomous path forbids it.** The worker skill says "never run
   `/loop-deploy` — deploy tasks do not exist in Phase A". A sensible
   decision when nothing was proven, which has outlived its reason.
3. **There is no trigger.** You saying "it is merged, deploy it" requires the
   reply arrow that does not exist yet.

The sequencing that follows: write one `.cc-deploy.yaml`, run `/loop-deploy`
by hand in a session, and find out whether the loop works before building a
trigger for it. Given it has never executed, that is where the risk is.

Not automated on merge, deliberately. Deploying is the most dangerous thing
this system can do — the only action your users see — and it should stay a
sentence you say, not a consequence of merging.

## It is something a stranger installs

Nemo is a repository you download and run on your own Mac. That is a product
decision with architectural teeth.

### Local by default, with one marked edge

Everything stays on the machine: memory, speech, the event log, the board
mirror, the conversation. The **only** outbound traffic is a model call, and
only when the user has chosen a hosted model. A user who runs local models
sends nothing anywhere.

This is not a privacy feature bolted on. It is why speech is mlx-whisper and
not an API, why memory is a vault on disk and not a service, and why the
dashboard binds the tailnet or loopback and refuses `0.0.0.0`. The boundary
should stay auditable in one place: if a reader cannot tell from the code
what leaves the machine, that is a bug.

### Requirements

**Obsidian, required.** Memory is a vault. Without one there is nowhere for
Nemo to remember anything, and a database would trade an inspectable,
portable memory for an opaque one.

**Linear, deliberately, with a shallow seam.** Nemo needs to know what is on
your plate, and for now that is Linear over MCP. Not abstracted: an interface
designed without a second implementation is invented rather than discovered,
and would encode a guess about what Jira and GitHub Issues have in common.
"Requires Linear" is an honest documented constraint.

The seam is kept shallow instead. Nemo reaches the work source through a
handful of operations — what is on my plate, get this issue, move it — rather
than scattering Linear-shaped assumptions through the code. When a second
source genuinely exists, the interface is derived from two real cases.

What that forbids today: widening the coupling. No new `linear_*`
configuration keys. The issue-key shape is already assumed in the launch
surface, the voice vocabulary and branch naming; each further place is cheap
now and tedious later.

**A model.** Ollama for local, or an API key for hosted. The tiers already
express this choice for coding flows; the assistant loop needs the same
switch.

### What that costs us today

Two things in this repository contradict the above and need fixing before
anyone else can use it. (Linear staying hardcoded is deliberate, not a
contradiction — see the requirement above.)

**Hermes is a prerequisite.** `make install-hermes` is the main install path,
so a stranger must install a third-party agent runtime before Nemo runs at
all. That is a heavy ask for a personal assistant, and it is the layer that
failed silently three times on the day this was written. Local-first and
easy-to-install both argue the same way: the assistant should not need it.

**A stranger's vault has no `_agent/` rules.** Decided: Nemo brings its own
convention and scaffolds it on first run — *when the vault does not already
have one*. Where a vault carries agent rules already, Nemo obeys them.

That order matters. This vault has a folder map, a frontmatter schema and
write instructions; an assistant that overwrote them with its own scheme would
be doing exactly what those rules exist to prevent. Scaffold when absent,
respect when present, and never silently restructure someone's second brain.

### Setup, as it must become

`make setup` should take someone from a cloned repository to a working Nemo:
check macOS and the toolchain, find or ask for the vault, scaffold the memory
convention inside it, offer local or hosted models, optionally connect a work
source over MCP, build and install the desktop face, install the dashboard
service, and then tell the user plainly what — if anything — will leave their
machine.

It should be honest when it cannot finish. Today's installer already refuses
rather than guessing when a path collides; the same standard applies here.

## Risks worth naming now

**Prompt injection gets sharper.** Nemo will read issue text, vault notes and
repository content, and will hold tools that spend money and write
files. Everything it reads is data, not instruction. The approval gate is what
makes this survivable, so it must not be weakened for convenience — the
temptation will be to auto-approve "safe" things, and today already showed
that `cat x; node -e "..."` defeats that classification.

**The local brain may not be enough for the loop.** `qwen3.6:35b-mlx` writes a
good morning brief. Agentic tool use with a real memory is harder, and a
wrong tool call is worse than a mediocre sentence. Expect the assistant to
want Claude even where the coding flows stay local.

**Hermes stays load-bearing under the parts that failed.** The board, the
dispatcher and Slack delivery are all Hermes. It is not worth replacing now,
but nothing new should depend on it, and the assistant should be built
outside it.

**Naming churn is not free.** The repository, package, service labels, config
keys and persona all say Ristretto. Renaming touches everything and collides
with in-flight work. Do it deliberately and last.

## Plan

Ordered by what closes the loop soonest, not by what is most interesting.

**1 — Deploy, by hand first.** Write one `.cc-deploy.yaml` for a real project
and run `/loop-deploy` in a session. It has never executed; find out whether
it works before anything is built on top of it. Cheap, and it is the end of
the loop you will use tomorrow.

**2 — The reply.** The morning brief asks a question nothing can hear. Give
Nemo its own agent loop with conversation state, so you can answer the brief —
in Slack or to the desktop face — and have it act: start that issue, or say
you would rather do something else. This is the single change that turns a
daily monologue into an assistant.

**3 — Remembering.** Distil each run into the project's vault note before the
worktree is reclaimed, and inject that note into the stages of the next run.
Wire the `knowledge_vault` setting, which has existed and been read by nothing
since it was added. This is what makes the setup compound instead of
rediscovering the same things.

**4 — "It is merged, deploy it."** Connect the reply to the deploy loop, gated
by the approval store. Now the loop is closed end to end: start it on the go,
review on a phone, ship by saying so.

**5 — Move the craft to wayworks.** Stage definitions leave `runner.py`; the
duplicate loop implementation goes away. A refactor that makes the codebase
honest rather than more capable, so it comes after the things that close the
loop.

**6 — The masterboard, the face, the rename.** Presentation and identity.
Real, and none of it changes what the system can do.

Dropped: "polish an idea". Frontier models in a session already do this
better, and the output is a markdown file that can be dropped into the vault
by hand.

Backlog: a CLI for iPad and phone. Terminus into a real session covers the
rare case; Slack covers notifications and premade actions, which is most of it.

## What exists already

Built and proven, and carried forward unchanged: the coding flows and tiers,
the event spine, approvals across two surfaces, the launch surface, the
doorbell, the fleet data layer, the desktop face and local speech. The
workshop is in good shape. What is missing is the assistant that directs it.
