# Contributing to Ristretto

Ristretto is a public, open-source project. All changes travel supervised
feature branches and pull requests — never direct pushes to `main`.

## Development workflow

1. Create a feature branch from `main`.
2. Run `make setup` once, then `make check` before every push or handoff —
   it is the exact script CI runs, so a green local run means a green CI run.
3. Before a release, `make public-check` (the publication gate) must also pass.
4. Keep secrets and machine-local identifiers outside git.
5. Update the relevant feature spec and changelog when behavior changes.
6. Open a pull request; never push changes directly to `main` unattended.

See [docs/development.md](docs/development.md) for the complete setup.

## Where behavior lives

- **Behavioral guardrails and process rules go in skills** (`hermes/skills/`).
  Skills are symlinked into installs, so every user gets the change on
  `make update`.
- **Voice and personal context go in the persona/config templates**
  (`hermes/SOUL.md`, `hermes/config.yaml`). These are copy-once seeds: they
  reach new installs only. A template change must ship with an
  **Upgrade notes** entry in `CHANGELOG.md` telling existing users what to
  port (see `docs/releases.md`).

## Commit style

Use concise conventional-style subjects such as:

```text
feat(ris): add configurable coding pipeline
fix(cron): suppress unchanged morning brief
docs: explain local development setup
```

## Safety boundary

Do not include tokens, private logs, personal task data, employer data, or
machine-specific paths in issues, tests, fixtures, documentation, or commits.
