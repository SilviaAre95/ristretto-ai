# Ristretto contributor context

Ristretto is an open-source, configurable personal operations assistant built
on Hermes Agent. Start with `AGENTS.md`, `README.md`,
`docs/project-status.md`, and `docs/features/INDEX.md`.

Use `make setup` and `make check`. Before a release, `make public-check` must
pass. Never commit credentials, live runtime state, personal channel IDs,
repository paths, issue exports, or vault content. Preserve supervised
feature-branch + pull-request behavior and never add auto-merge.
