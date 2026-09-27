# Zam — the roadmap

**Status:** active · **Written:** 2026-09-03 · **Corrected:** 2026-09-27 ·
The thing to work from.

This is the plan for building Zam, distilled from the session where the
vision was set. The *reasoning* lives in `docs/zam-architecture.md`; this is
the ordered work. Start at the top.

> **What the 2026-09-27 correction changed.** Two of the three missing arrows
> had stopped matching the code, and this file was being planned from anyway.
> The reply is built and wired to four surfaces; remember's reader shipped and
> its writer did not; Phase 0's seam contract test exists and passes. Only
> deploy is still unbuilt as described. Every claim below was checked against
> the code on 2026-09-27 rather than carried forward. The discipline worth
> keeping: an arrow marked ❌ that is actually built costs more than one marked
> ✅ that is broken, because nobody goes looking.

## The vision, in one paragraph

I wake up and Zam tells me what's on my plate — the projects, the priorities,
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
morning      Zam says what matters today           ✅ the brief does this
you reply    "start the second one" / "go do X"    🟡 built, never dogfooded
dispatch     work runs, following wayworks' loop   ✅ works
report       "here's the PR, here's what I did"    ✅ works (to the board)
you review   read on a phone, merge                ✅ you
"deploy it"  ship, watch prod, confirm or fix      ❌ blocked three ways
remember     what was learned → the vault          🟡 it reads; nothing writes
```

One arrow is missing outright — deploy. Two are half-built: the reply exists
and has never been used in anger, and remember reads but does not write. That
is still the whole roadmap, but two-thirds of it is now finishing and proving
rather than building, and that is different work with a different cost.

## What is true today

**Built and proven** — dispatch (dashboard `/launch`, from the phone too),
unattended runs, multi-model tiers (reviewer never the builder), the approval
gate on two surfaces with a reason box, the doorbell, the fleet view, local
speech (STT; there is no TTS anywhere in the repository), the desktop face as
a window, and the morning brief. The workshop is solid.

**Built, not proven** — the reply. `cuzam/assistant/loop.py` is a real agent
loop: one provider resolved from `assistant_provider`, driven as `claude -p`
over Zam's own MCP tool server, conversation continuity through
`--session-id`/`--resume`, and five tools including `launch_run` and
`propose_merge`. It is reached from `cuzam chat`, the dashboard, the desktop
face and Slack. It has never been dogfooded, so whether it is *good* is
unknown. The contract is `docs/features/zam-assistant.md`.

**Half built** — remember. The reader is wired: `context.py` searches the
vault by issue key and injects up to three notes into `context.md`, which
reaches every stage. The writer is absent, and `cuzam/assistant/vault.py` is
read-only by design and says so.

**Designed, not built** — deploy. No `.cc-deploy.yaml` exists anywhere;
`cuzam/seam.py` declares the filename so the contract covers it, and nothing
reads or writes one.

**The honest gap** — no longer that the assistant is a proxy. It is that the
assistant has never held a real conversation. The loop is built, wired to four
surfaces, and entirely unmeasured. Unbuilt is a plan; unproven is an hour.

## Principles that constrain every phase

- **Local by default.** Memory, speech, events, conversation stay on the
  machine. The only outbound traffic is a model call the user chose. If a
  reader can't tell from the code what leaves the machine, that's a bug.
- **Zam proposes; you commit.** Nothing mutating happens on a model's say-so
  or on a transcription. The approval store is the commit primitive.
- **Vault content is data, never instructions.** Once runs read what runs
  wrote, that channel can carry an attack. Name it in every prompt.
- **Don't let the tool become the project.** Prefer running real work to
  extending the harness. When it works, use it.

## Phases

Ordered so each one ships something usable on its own. The phase numbers are
the original ranking and are kept for continuity; the order actually being
worked is at the bottom of this file, under *The order, decided 2026-09-27*.
Phase 2's reader has since shipped, so the note that used to stand here —
memory is the highest-value item and can be pulled ahead of Phase 1 — has
already half happened. What is left of Phase 2 is the writer, and it is still
independent of everything else.

### Phase 0 — housekeeping (mostly done)

- [x] User-facing rename to Zam
- [x] Real write-protection floor in global settings (`Edit(.env|.git)`)
- [ ] Sweep inert deny rules from the remaining repos *(kaffecard, crema PRs open)*
- [ ] Fix the `Bash(sudo *)` glob form flagged in wayworks#45
- [x] Contract test on the wayworks seam (`.cc-verify` etc.) so a rename there
      fails loudly here — `cuzam/seam.py` declares the names once,
      `hermes/tests/seam_contract_test.py` asserts wayworks' `harness-init`
      still creates them and that no module re-hardcodes them. It skips when
      wayworks is not a sibling checkout, which is not the case here.
      *(done; found unchecked 2026-09-27)*

### Phase 1 — the reply

**Status 2026-09-27: built, not proven.** The loop shipped and is wired. What
remains is to use it, plus one absent intent and one real continuity gap.

Give Zam its own agent loop so the morning brief becomes a conversation.
Answer it — in Slack or to the face — and have it act.

- ✅ A real agent loop (own conversation state), replacing `dash/chat.py` —
  shipped as `cuzam/assistant/loop.py`; `dash/chat.py` is gone
- 🟡 Three intents from one reply: **answer the brief** ✅ (it reads the fleet
  and the vault through its own tools); **start known work** ✅ (`launch_run`,
  which requires an explicit project because issue keys are ambiguous across
  repositories); **describe new work** ❌ — `look into why the build is slow`
  should scaffold a Linear issue and then dispatch, and there is no Linear
  tool in the table at all
- ❌ Same conversation across the face, the dashboard, and Slack — and the gap
  is bigger than one shared thread. The CLI and Slack hand over a durable name
  (`--conversation`, the channel id) which the loop maps to a session on disk,
  so each holds a thread; they are two threads, not one. **The dashboard and
  the face hold nothing:** both post `{message}` alone and ignore the `session`
  the endpoint hands back, so every turn there is a fresh conversation. The
  endpoint takes a `session` and so does `loop.ask`, which is why this reads as
  working from the Python side alone — it was described that way in this file
  until the claim was checked against the two clients on 2026-09-27. Wiring
  them up waits on issue #80: a first turn that fails currently poisons the
  session a name maps to, and in Slack that wedges a channel for good.
- ~~Launch-from-Slack~~ ✅ done (`!zam-start`) — the deterministic half of the
  reply. What remains below is the conversational half.
- **Decided: v1 runs on Claude, built provider-configurable.** The loop's hard
  skill is reliable tool-calling — emitting a correct `launch(...)` and not
  hallucinating its arguments — which is where the local brain is weakest and
  Claude is proven, and where a wrong call spends money or starts a run with no
  reviewer to catch it (unlike the tiers). Claude first isolates the variable:
  a bug is then the loop design, not the model fumbling a call.

  **Guardrail — build it as a configured provider, never hardcoded.** The loop
  reads `assistant_provider` from config; Claude is the value, not a constant.
  The providers already exist (`claude`, `local-brain`), so this costs nothing
  now and makes the local switch one line later instead of a rewrite. Do this
  from the first commit.

  **Sequencing, so "Claude for v1" doesn't become permanent by accident:**
  ship on Claude → get the loop correct → swap `assistant_provider` to
  `local-brain` and find out what breaks. Never dogfooding local is how the
  privacy pitch quietly rots.

  **Shipped as specified** (2026-09-27): the loop resolves
  `instance.assistant_provider` and falls back to `claude` only when the key
  is unset, which it is in `cuzam.yaml`. So the guardrail held — Claude is the
  value, not a constant — and the switch is genuinely one line. The switch has
  not been taken, and the trigger for taking it is still unstated; that is now
  an open question on `local-brain` rather than a line in a plan.

  **What running on Claude means, stated plainly:** the assistant touches the
  most personal context in the system — the vault, the priorities, the
  conversation itself. On Claude, all of that goes to Anthropic. For the owner
  testing v1 that is a fine trade; for the downloadable product, local stays
  the documented default. The claim is "it *can* run entirely local", not "it
  does for everyone".

  One consequence was missed until 2026-09-27 and is worth naming: the shipped
  default is cloud, so "local stays the documented default" was not true of
  the code. `local-brain`'s acceptance criteria said no cloud LLM orchestrates,
  while this loop orchestrated on Claude out of the box. Those criteria now
  name the Hermes path they actually describe.

**What remains in Phase 1: dogfood it.** Have a real conversation, ask it to
start something, watch what breaks. It is the cheapest information available —
the code is already written — and it decides whether Phase 1 needs finishing
or only fixing. Nothing below should be sequenced off an assumption about a
loop nobody has talked to.

### Phase 2 — remember (the reader shipped; the writer is the gap)

Make the setup compound. This is the "better every time" that everything else
is in service of.

- ✅ Reader: inject a project's vault note (summary first, body capped) into
  each stage prompt — `context.vault_notes()` searches by issue key, reads up
  to three notes, clips each, and renders them into `context.md`, which
  reaches every stage. Searched by issue key alone on purpose: a looser query
  pulls in whatever shares a word with the title, and a plan built on the
  wrong note is worse than a plan built on none.
- ❌ Writer: at the finish stage, distil the run — what was decided, what the
  review found, the PR — into the project's note **before the worktree is
  reclaimed** (today those artifacts are deleted). `cuzam/assistant/vault.py`
  is read-only by design and says so; this is the one pillar where the gap is
  real code rather than proof.
- ✅ Wire the `knowledge_vault` setting, which has been read by nothing since
  it was added — done; it is read by the reader above and by the assistant's
  `search_memory` and `read_note` tools.
- 🟡 The four curation guards: what prunes, what goes stale (date every fact),
  observed-vs-decided, and vault-content-is-data. **Vault-content-is-data is
  in place** on all three paths that carry untrusted text — `runner.py`, the
  rendered `context.md`, and the assistant's system prompt. The other three
  are curation rules for the writer and land with it.
- **Decide first:** the note shape Zam scaffolds into a fresh vault, and that
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
definitions Zam executes — the relationship it already has with `.cc-verify`.
A refactor: makes the codebase honest, not more capable. After the loop is
closed.

### Phase 5 — presence and identity

Real, and none of it changes what the system can *do*. It changes whether the
system is something you live with. Scheduled 2026-09-27 to run after Phase 1
is dogfooded, on the owner's decision and against this file's own ranking —
which is recorded here so the disagreement is visible rather than lost.

"The desktop face" appears under **Built and proven** above and "Zam's actual
face" appears here, which reads as a contradiction until you look. Both are
true of different things: `zam/Zam.swift` is a built window — 329 lines,
`.accessory`, floats above normal windows, posts to the dashboard's `/voice`
and `/chat` and renders the answer. What Phase 5 asks for is the part that is
not a window.

- **TTS, so Zam talks back.** The one genuinely absent half of voice. STT is
  done and local — `cuzam/voice.py`, mlx-whisper, `POST /voice`, warm-up on
  start, push-to-talk — and there is no TTS anywhere in the repository. Keep
  it local, for the same reason the brain is local. **The settled rule to
  honour and not re-open: voice composes, a click commits.**
  `docs/zam-feasibility.md` records why, and push-to-talk is why the
  always-open-microphone objection does not apply.
- **The face's quit affordance.** `.accessory` means no Dock icon and no menu
  bar, and there is no quit path — confirmed by grep. It is furniture you
  cannot put down.
- **The masterboard reframe.** From a fleet of runs to *what's on my plate /
  running / needs me / remembered*. **Hard constraint:** `fleet-view`'s
  non-goals include "NOT a second definition of a live run". `cuzam/runs.py`
  and `scripts/live-runs.sh` are the only two answers to what a live run is,
  pinned to each other by a contract test. The reframe must not add a third.
- **The deep rename** (package, env vars, service labels, GitHub repo, Slack
  bot name). Deliberate work, not a side effect of anything else. The agent
  memory directory is keyed on the checkout path and moves in the same step.

## The order, decided 2026-09-27

The previous recommendation here was "Phase 2, the reader half." That shipped.
A plan that recommends finished work is worse than one that recommends
nothing, because it reads as current.

**1 — Dogfood the reply.** Free, because it is built. One real conversation:
ask what is running, ask it to start something, watch what breaks. It is the
cheapest information available and it decides whether Phase 1 needs finishing
or only fixing.

**2 — Phase 5, presence.** TTS, then the face's quit affordance, then the
masterboard reframe. This runs ahead of Phases 2–4 by decision, against this
file's own ranking.

**The tension, stated rather than resolved quietly.** This roadmap ranks
Phase 5 last and says none of it changes what the system can do. That
sentence is still true and it is still not the whole argument: presence is the
part that gets used, and a system you do not reach for compounds nothing no
matter how much it can do. The counter-case is honest too — the writer half of
remember is the one place a pillar is missing *code* rather than proof, and
every day it is absent, finished runs are reclaimed and what they learned is
deleted. That cost is silent and it is ongoing.

**So: Phases 2–4 are deferred, not reordered.** The writer, deploy, and the
move to wayworks keep their sequence and resume after presence. Deploy stays
the only arrow that is unbuilt as described, and `/loop-deploy` has still
never been executed — the roadmap's advice to run it by hand once before
building on it is unchanged and cheap.

## Explicitly not doing

- "Polish an idea" — frontier models in a session do it better; the output is
  a note you drop in the vault by hand.
- Abstracting Linear — one work source, shallow seam, until a second exists.
- A phone/iPad CLI — backlog. Terminus covers the rare case; Slack covers
  notifications and premade actions.
- Replacing Hermes — it keeps the board, dispatcher and Slack transport.
  Nothing new depends on it; it shrinks as it earns.
