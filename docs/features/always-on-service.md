---
id: always-on-service
title: Always-On Service
status: implemented  # proposed | in-progress | implemented | deprecated
created_at: 2026-07-05
last_modified: 2026-07-17
owner: project
depends_on: []
acceptance_criteria:
  - Runs as a launchd service surviving logout
  - Lungo holds a wake assertion while unattended
non_goals:
  - "NOT changing `pmset` without approval"
  - NOT installing or running without explicit opt-in
---

# Always-On Service

## Summary

The gateway can run as a background launchd service so Ris continues after terminal closure. Wake management remains a separate explicit user choice.

## Behavior

On macOS, `hermes gateway install` creates a launchd service that survives terminal closure. Ristretto does not change `pmset`; users who need an always-awake workstation must choose and manage that separately.

## Out of scope

- NOT changing `pmset` without approval: any change to the Mac's power management settings requires explicit approval — it is not done automatically as a side effect of this feature.
- NOT installing or running without explicit opt-in: the default installer leaves the service unchanged; `--service` is required.

## Open questions

None.

## Implementation notes (optional)

- Service: `ai.hermes.gateway.plist`
- Manage with `hermes gateway status` and `hermes gateway restart`.

## It deploys itself

The service runs with `--reload`, watching the `ristretto` package only.
Editing docs or tests does not bounce a server someone is reading; changing
the code does.

This is not a convenience. The dashboard served code older than its checkout
four times in one day — a live run reported as stalled because the process
predated the fix, the approval banner missing for the same reason, a question
mis-transcribed after transcription had been fixed, and a footer displaying
the commit that contained the fix while running without it. Each time the
remedy was "restart it by hand", which is a thing to forget, not a remedy.

The footer still stamps the commit the process loaded and says plainly when
the checkout has moved ahead — belt as well as braces, because a reloader
that dies leaves a server that looks fine.
