# Ristretto contributor context

Ristretto is an open-source, configurable personal operations assistant built
on Hermes Agent. It integrates Slack, Linear, local or cloud model providers,
durable coding workers, approval gates, and named multi-model coding flows.

## Read first

- `README.md` — product overview and installation status.
- `docs/project-status.md` — public implementation status and roadmap.
- `docs/open-source-readiness.md` — publication and privacy guarantees.
- `docs/features/INDEX.md` — behavior contracts and non-goals.

## Development

Run `make setup` once, then `make check`. Run `make public-check` before any
release. Never commit credentials, live Hermes state, user channel IDs,
repository paths, issue exports, or knowledge-vault content.

## Guardrails

- Coding work stops at a feature-branch pull request; never auto-merge.
- Risky, destructive, costly, secret-bearing, or production actions require
  explicit user approval.
- Employer systems are read-only unless policy and authorization are confirmed.
- Sensitive-data projects require explicit approval.
- Prefer minimal root-cause fixes and preserve backward compatibility for the
  `classic` flow.
