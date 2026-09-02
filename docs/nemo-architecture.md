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

What Nemo needs is organised around **your work**, which lives in Linear and
in the vault. A run is something Nemo *does about* a piece of work, the way
sending a Slack message is. It is not the subject.

Concretely, that inverts three things:

| | today | Nemo |
|---|---|---|
| The board | Hermes kanban, shown as "the fleet" | Linear. Hermes' queue becomes invisible plumbing |
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
 Linear    Obsidian    Flows    Approvals    Fleet      Slack
the work    memory    execute     gate       status     reach
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

Nemo needs its own loop: conversation state, a memory it controls, and an
explicit tool boundary. Proxying Hermes' agent means memory, tool policy and
continuity are defined by another project — and the day this was written,
that project dropped inbound Slack messages for hours without a log line.

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

## Risks worth naming now

**Prompt injection gets sharper.** Nemo will read Linear issue text, vault
notes and repository content, and will hold tools that spend money and write
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
Its own agent loop, replacing the proxy. Tools: Linear (read), vault
(read/write), fleet (read). Conversation persists and is shared across the
desktop face, the dashboard and Slack. This is the phase that makes Nemo an
assistant rather than a status endpoint.

**2 — "Let's kick this off."**
Intent to proposal to commit, on the existing approval store. Nemo can launch
a flow, stop one, and answer a gate — always as something you confirm. Linear
is updated as work moves.

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
