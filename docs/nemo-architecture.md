# Nemo — architecture and handover

**Status:** proposed · **Written:** 2026-09-02 · Supersedes the framing in
`docs/project-status.md`, which describes a coding harness.

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

**1 — Nemo answers "what do I have on my table?" with memory.**
Its own agent loop, replacing the proxy. Tools: the work source (read), the vault
(read/write), the fleet (read). Conversation persists and is shared across the
desktop face, the dashboard and Slack. This is the phase that makes Nemo an
assistant rather than a status endpoint.

**2 — "Let's kick this off."**
Intent to proposal to commit, on the existing approval store. Nemo can launch
a flow, stop one, and answer a gate — always as something you confirm. The
work source is updated as work moves.

**3 — The masterboard.**
Reframe the dashboard from a fleet of runs to: what is on my table, what is
running, what needs me, what Nemo remembers. The run list becomes one panel,
not the page.

**4 — The rename.**
Repository, package, service labels, persona. Mechanical, and last.

**Backlog:** a CLI for iPad and phone. Deliberately deferred — Terminus into
a real session covers the rare case, and Slack covers notifications and
premade actions, which is most of it.

## What exists already

Built and proven, and carried forward unchanged: the coding flows and tiers,
the event spine, approvals across two surfaces, the launch surface, the
doorbell, the fleet data layer, the desktop face and local speech. The
workshop is in good shape. What is missing is the assistant that directs it.
