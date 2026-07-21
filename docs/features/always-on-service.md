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
