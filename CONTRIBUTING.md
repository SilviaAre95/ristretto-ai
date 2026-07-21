# Contributing to Ristretto

Ristretto is preparing for its first public release. Until the publication
gate passes, contributions should be made on local feature branches.

## Development workflow

1. Create a feature branch from `main`.
2. Run `make setup` once, then `make check` before every handoff.
3. Keep secrets and machine-local identifiers outside git.
4. Update the relevant feature spec and changelog when behavior changes.
5. Open a pull request; never push changes directly to `main` unattended.

See [docs/development.md](docs/development.md) for the complete setup.

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
