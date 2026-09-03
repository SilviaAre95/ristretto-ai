# Nemo — feasibility check

> Superseded by `docs/nemo-architecture.md` for scope and purpose. This note
> remains the record of what was verified about voice, presence and authority,
> and its conclusions still hold.

**Status:** v1 built · **Created:** 2026-09-02 · **Owner's note, reviewed**

Nemo is the working name for the embodied version of Ristretto: an
always-present character on the Mac Studio you can talk to out loud and hand
work to, rather than a bot you message.

This is a feasibility check, not a plan. The point was to find out what is
already solved, what is not, and what to verify before committing time.

Related vault notes: `01-plan`, `04-model-routing-plan`, `local-ai-lab`.

## Verdict

Possible, and smaller than it looks. Hermes already covers three of the four
layers. What is left is presence, an input trigger, and knowing when to
speak — and the last one is less unsolved than it first appeared.

## The four layers

"Clippy that lives in my computer" is four separate systems wearing one
costume.

| Layer | What it means | Status |
|-------|---------------|--------|
| **Hands** — does things on the machine | shell, files, gcloud, Claude Code | Hermes, with caveats (below) |
| **Ears/mouth** — talk to it, it talks back | VAD → STT → LLM → TTS | Hermes, and STT is already local |
| **Body** — visible character on screen | transparent always-on-top window | build |
| **Eyes + judgment** — notices, speaks unprompted | screen awareness + interrupt filter | partly already built (below) |

The first three are integration work. The fourth is the thing that made
Clippy Clippy.

## Findings from the review

### STT is already local

Hermes ships `stt.enabled: true` with a local whisper (`base`) alongside the
OpenAI path. The "ears" layer is a model-size choice, not an architecture
gap. This is better than the first draft of this note assumed.

### "Hands" is the least solid layer, not the most

Hermes has the capabilities. What it does not have is reliable, observable
delivery. Observed in a single day of use:

- Slack Socket Mode wedged for hours while still reporting "connected"
- inbound messages silently not delivered, with no log line either way
- the dashboard served day-old code because nothing restarted it
- every notification link pointed at `127.0.0.1` because a cron PATH lacked
  one binary, and the fallback was silent

This matters more for Nemo than for a chat bot. A bot that misses a message
is annoying; a character on screen that hears you and does nothing is broken
in a way people stop forgiving. Treat this layer as "capable, and needing a
supervision layer that does not exist yet".

### The interrupt filter is already half-built

`ristretto/doorbell.py` defines a closed `MILESTONES` set, and the comment on
it states the whole Clippy thesis:

> a run emits six of each, and a channel that pings twelve times per task is
> a channel nobody reads

That is an interruption policy: outcomes and trouble interrupt, progress does
not. Nemo v1 does not need screen awareness — it needs to surface exactly the
events the doorbell already rings on.

The genuinely unsolved part is narrower than the note first claimed. It is
not *whether to speak*; it is *noticing things nobody told it about*. That is
a later, smaller-scoped problem, and it can wait for real usage.

### Nemo is a client, not a fourth system

The event spine, approvals, fleet data and `/chat` already exist and are
running. Nemo is another surface on the same core, the way the dashboard is.
Framing it as four independent layers risks rebuilding `ristretto/dash/`.

## Voice and authority

The open question was whether voice may answer an approval gate. The gate
exists so that *a human decided*; "human" and "audible in the room" are not
the same set.

Resolved as follows.

**Push-to-talk changes the comparison.** The objection is against an
always-open microphone, not against voice:

- Dashboard approval requires being on the tailnet. There is no login —
  anyone who can reach the address can press Approve.
- Push-to-talk approval requires physical access to the machine to press the
  button.

Physical access is the stricter bar. Voice behind a button is therefore a
*stronger* channel than the one already shipped, not a weaker one.

**What remains is an accident model, not an attacker model.** While the mic
is open it captures the room: a call, a podcast, someone talking over you.

**The rule:** voice composes, a click commits. Nemo transcribes, writes back
what it understood, and nothing mutating happens until it is pressed. Voice
becomes navigation and drafting; the commit stays a deliberate physical act.
A stray "yeah, approve that" from a video call can never decide anything.

This is the same feature as the v1 interaction ("I talk, he writes"), so the
safety property costs nothing extra.

**No mutating action commits on transcription alone.**

## v1 scope

Decided:

- **No wake word.** Start on demand — a button or hotkey.
- **Nemo does not speak.** You talk, Nemo writes, in a conversation globe.
- **No TTS.**

```
button/hotkey → mic → whisper (local) → text
    → Ris (the existing /chat endpoint)
    → reply rendered in the globe
    ↑
doorbell MILESTONES → the same globe, unprompted
```

The only genuinely new pieces are the window and the hotkey. Everything
behind it is built and running.

**Suggested shape:** a small native shell (transparent always-on-top panel)
hosting a web view of a Nemo page served by the existing dashboard server.
That reuses SSE, `/chat` and the approval routes rather than reimplementing
them, and keeps native code to three things: window, hotkey, microphone. A
separate app with its own state would mean maintaining two clients of one
core.

## Dependency

Nemo v1 makes the dashboard's read-only limit the binding constraint. "I
talk, he writes" is a status reader unless Ris can act on what was said, and
acting means launching work. The launch surface is therefore a prerequisite
for Nemo being more than a nicer way to read the fleet view — not a competing
priority.

## Open questions

- Where the native/web boundary sits, precisely.
- What the globe looks like when idle, and whether idle is visible at all.
- Whether unprompted milestones should ever animate or only appear.
- Screen awareness: deferred, and should stay deferred until v1 has been
  lived with.

## v1, as built (2026-09-02)

`nemo/Nemo.swift`, built by `scripts/build-nemo.sh` into `Nemo.app`.

An `NSPanel` at `.floating` level with `canJoinAllSpaces` and
`fullScreenAuxiliary`, so it is present over every application and every
Space — including full-screen ones, which is when you are actually working.
`nonactivatingPanel` so clicking it never pulls focus out of what you were
doing; `LSUIElement` so there is no Dock icon and no app to switch to.

**Hold the mouse on Nemo to talk.** The microphone opens on mouse-down and
closes on mouse-up. There is no wake word and no voice-activity detector, so
there is no window in which a room, a call or a video can be recorded without
a deliberate act.

The recording goes to the dashboard's `/voice`, transcribed on this machine
by mlx-whisper (`whisper-base-mlx`, ~0.1s warm). The text is shown first, then
sent to `/chat`, and the reply appears under it. Seeing what it heard before
what it thinks means a bad transcription is obvious immediately rather than
explaining a strange answer afterwards.

A badge on the face carries the number of decisions waiting on a person,
polled from `/nemo/state` every 20 seconds.

Nemo has no tools and no board access. It posts to two endpoints and renders
what comes back; anything that changes the world still goes through the
approval gate.

### Bundled, not a bare binary

macOS refuses the microphone to an executable without a bundle identifier —
TCC has nothing to attribute the request to and no sentence to show. Hence
`Info.plist`, `NSMicrophoneUsageDescription`, and an ad-hoc signature.

### Not done

- The dashboard address is read from `~/.ristretto/dash-url`, written by the
  installer. It is a fact about the machine and does not belong in the repo.
- Voice from a phone needs HTTPS on the tailnet (`CertDomains` is currently
  empty); browsers refuse microphone access on a non-secure origin. Text chat
  already works there.
- The avatar is a circle with a letter in it. It is a placeholder for a face.
- No TTS. You talk, Nemo writes.
