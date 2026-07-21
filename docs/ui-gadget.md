# UI Gadget Concept: Ristretto Shot

## Recommendation

Build a small macOS menu-bar companion rather than a full dashboard first.
Slack remains the conversational surface; the gadget is the fast operational
control surface for status, approvals, and model flows.

```text
┌─ ☕ Ris ─────────────────────────────┐
│ ● Running        Local brain: Qwen │
│                                      │
│ Current work                         │
│ PROJ-123  Building locally     62%   │
│ Claude plan → Local build → Codex    │
│                                      │
│ [Open in Slack]       [Stop safely]  │
├──────────────────────────────────────┤
│ Quick run                            │
│ Issue  [PROJ-___]                    │
│ Flow   [Balanced ▾]      [Run]       │
├──────────────────────────────────────┤
│ Flows                                │
│ Balanced   Claude → Local → Codex    │
│ Quality    Claude → Claude → Codex   │
│ Offline    Local  → Local  → Local   │
│                         [Edit flows] │
├──────────────────────────────────────┤
│ Gateway ✓  Slack ✓  Linear ✓        │
│ [Logs] [Doctor] [Pause] [Settings]   │
└──────────────────────────────────────┘
```

## First release scope

- Gateway health and current model
- Current/queued durable task status
- One-click safe stop and pause
- Open the relevant Slack thread or pull request
- Choose a named coding-flow preset when queuing an issue
- Surface pending approvals without duplicating the approval decision outside
  Slack

## Later flow editor

The editor should show a simple stage graph: `Plan → Build → Review → Verify →
PR`. Each stage chooses a configured provider/model, timeout, mutation flag,
declared artifact inputs/output, and fallback. It reads and writes schema
version 1 from `ristretto.yaml`; saving must pass the same validation as
`ristretto validate`. Users can add stages and save custom presets without
editing YAML, while an advanced view exposes the generated configuration.

The gadget must talk to a local Ristretto/Hermes API and contain no provider or
Slack credentials itself.
