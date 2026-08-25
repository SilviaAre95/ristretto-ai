---
id: config-in-repo
title: Config In Repo
status: implemented  # proposed | in-progress | implemented | deprecated
created_at: 2026-07-05
last_modified: 2026-07-27
owner: project
depends_on: []
acceptance_criteria:
  - Public Hermes baselines, skills, scripts, and examples have canonical sources under `hermes/`
  - "`~/.hermes/.env` is never committed"
  - "`git grep xoxb-` is clean"
non_goals:
  - NOT committing secrets
  - NOT versioning the Hermes engine code or runtime state
---

# Config In Repo

## Summary

Public Hermes baselines and Ristretto behavior are versioned in the repository. The installer copies or links only managed assets while user configuration, credentials, runtime state, and jobs remain local.

## Behavior

Ristretto's own configuration is layered rather than copied. `providers` and
`flows` describe how Ristretto works and are read from the shipped
`ristretto.yaml`; the user's `~/.config/ristretto/config.yaml` holds only what
describes their machine — `instance`, `repositories`, and any deliberate
override. A user entry replaces the shipped one by name, so overriding a
single provider does not pin the rest. `ristretto migrate` reports which
entries a pre-existing config is holding a private copy of, shows the
field-level differences for those that diverge, and rewrites the file with
`--force` (`--adopt` takes the shipped version for the diverging ones too).
A difference cannot distinguish a deliberate change from an out-of-date copy,
so it is reported rather than guessed at.

`hermes/SOUL.md`, `hermes/config.yaml`, skills, scripts, and `jobs.example.json` are public inputs. Existing user config and persona are never overwritten. Skills are linked as managed code; cron scripts are copied because Hermes requires them inside `~/.hermes/scripts`. Secrets remain only in `~/.hermes/.env`. Live cron state is never tracked.

The installer records which template version seeded the user's persona and config (`~/.hermes/.template-seeds`). `make update` pulls the release, re-runs the installers, reports — never merges — template drift via `scripts/template-drift.sh`, and restarts the gateway; the user reviews reported drift against the changelog's Upgrade notes and acknowledges with `--ack`.

## Out of scope

- NOT committing secrets: no token, password, or credential is ever added to the repo; `.env` and equivalent files are gitignored and excluded by convention, not just by accident.
- NOT versioning the Hermes engine code or runtime state: the Hermes Agent runtime itself (the open-source engine) and its runtime/session state are not tracked in this repo — only the config that customizes it.

## Open questions

## Implementation notes (optional)

See the installation section in `README.md`.
