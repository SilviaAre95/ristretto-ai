# Nemo — the roadmap

**Status:** active · **Written:** 2026-09-03 · The thing to work from.

This is the plan for building Nemo, distilled from the session where the
vision was set. The *reasoning* lives in `docs/nemo-architecture.md`; this is
the ordered work. Start at the top.

## The vision, in one paragraph

I wake up and Nemo tells me what's on my plate — the projects, the priorities,
what's in flight. I answer him: start this one, not that, actually go look
into this other thing. He kicks the work off and it runs on my computer at
home while I'm out. When it's done he shows me the PR and what he did,
somewhere I can see and track it. I review it on my phone, approve it, and
then I say *deploy it* — and he ships it, watches production, and tells me it's
live and working, or that it needs a fix. Everything he learns goes into my
Obsidian vault, so he's better every time. He runs on my machine; nothing
leaves it unless I choose a hosted model. And he's there, floating on my
screen, when I need him.

## The loop

```
morning     Nemo says what matters today          ✅ the brief does this
you reply   "start the second one" / "go do X"    ❌ nothing hears you
dispatch    work runs, following wayworks' loop    ✅ works
report      "here's the PR, here's what I did"     ✅ works (to the board)
you review  read on a phone, merge                 ✅ you
"deploy it" ship, watch prod, confirm or fix       ❌ blocked three ways
remember    what was learned → the vault           ❌ nothing writes it
```

Three arrows are missing. They are the whole roadmap. Everything between them
already works.

## What is true today

**Built and proven** — dispatch (dashboard `/launch`, from the phone too),
unattended runs, multi-model tiers (reviewer never the builder), the approval
gate on two surfaces with a reason box, the doorbell, the fleet view, local
speech, the desktop face, and the morning brief. The workshop is solid.

**Designed, not built** — the reply, vault memory, deploy.

**The honest gap** — the assistant itself is 104 lines that shell Hermes and
return the answer. The thing the product is named after is a proxy.

## Principles that constrain every phase

- **Local by default.** Memory, speech, events, conversation stay on the
  machine. The only outbound traffic is a model call the user chose. If a
  reader can't tell from the code what leaves the machine, that's a bug.
- **Nemo proposes; you commit.** Nothing mutating happens on a model's say-so
  or on a transcription. The approval store is the commit primitive.
- **Vault content is data, never instructions.** Once runs read what runs
  wrote, that channel can carry an attack. Name it in every prompt.
- **Don't let the tool become the project.** Prefer running real work to
  extending the harness. When it works, use it.

## Phases

Ordered so each one ships something usable on its own. Memory (Phase 2) is the
highest-value item and is independent — it can be pulled ahead of Phase 1 if
that's the itch.

### Phase 0 — housekeeping (mostly done)

- [x] User-facing rename to Nemo
- [x] Real write-protection floor in global settings (`Edit(.env|.git)`)
- [ ] Sweep inert deny rules from the remaining repos *(kaffecard, crema PRs open)*
- [ ] Fix the `Bash(sudo *)` glob form flagged in wayworks#45
- [ ] Contract test on the wayworks seam (`.cc-verify` etc.) so a rename there
      fails loudly here

### Phase 1 — the reply

Give Nemo its own agent loop so the morning brief becomes a conversation.
Answer it — in Slack or to the face — and have it act.

- A real agent loop (own conversation state), replacing `dash/chat.py`
- Three intents from one reply: answer the brief, start known work
  (`start XARI-26`), describe new work (`look into why the build is slow` →
  **scaffold a Linear issue first**, then dispatch — `mcp_linear_save_issue`
  already exists)
- Same conversation across the face, the dashboard, and Slack
- Launch-from-Slack (Slack can answer today but not start)
- **Decide first:** which model runs the loop — local brain or Claude. A wrong
  tool call is worse than a mediocre sentence.

### Phase 2 — remember (highest value, independent)

Make the setup compound. This is the "better every time" that everything else
is in service of.

- Reader: inject a project's vault note (summary first, body capped) into each
  stage prompt
- Writer: at the finish stage, distil the run — what was decided, what the
  review found, the PR — into the project's note **before the worktree is
  reclaimed** (today those artifacts are deleted)
- Wire the `knowledge_vault` setting, which has been read by nothing since it
  was added
- The four curation guards: what prunes, what goes stale (date every fact),
  observed-vs-decided, and vault-content-is-data
- **Decide first:** the note shape Nemo scaffolds into a fresh vault, and that
  it obeys an existing vault's `_agent/` rules rather than overwriting them

### Phase 3 — deploy

Close the loop at a working deployment, not a PR.

- Write one `.cc-deploy.yaml` and run `/loop-deploy` **by hand** — it has
  never executed; find out if it works before building on it
- Lift the Phase-A block in the worker skill
- Connect "it's merged, deploy it" to the deploy loop, through the approval
  gate — never automatic on merge
- `harness-init` scaffolds a `.cc-deploy.yaml` template (wayworks)

### Phase 4 — move the craft to wayworks

Kill the duplicated loop. `runner.py`'s stage instructions become wayworks
definitions Nemo executes — the relationship it already has with `.cc-verify`.
A refactor: makes the codebase honest, not more capable. After the loop is
closed.

### Phase 5 — presence and identity

The masterboard reframe (from a fleet of runs to what's on my plate / running
/ needs me / remembered), Nemo's actual face and its quit affordance, and the
deep rename (package, env vars, service labels, GitHub repo, Slack bot name).
Real, and none of it changes what the system can do.

## Recommended first move

**Phase 2, the reader half.** It is small, independent of everything else, and
it is the piece that makes the vision's core promise — better every time —
start to be true. One project note injected into one run's plan stage is a
day's work and immediately visible. The writer half and curation follow.

If the itch is instead to *feel* the assistant, Phase 1's reply is the more
satisfying first build. Both are defensible; neither waits on the other.

## Explicitly not doing

- "Polish an idea" — frontier models in a session do it better; the output is
  a note you drop in the vault by hand.
- Abstracting Linear — one work source, shallow seam, until a second exists.
- A phone/iPad CLI — backlog. Terminus covers the rare case; Slack covers
  notifications and premade actions.
- Replacing Hermes — it keeps the board, dispatcher and Slack transport.
  Nothing new depends on it; it shrinks as it earns.
