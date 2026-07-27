# Changelog

All notable changes to Ristretto will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and releases use [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- One-command user update path: `make update` pulls the release
  (`--ff-only`), re-runs the idempotent installers to refresh symlinked
  assets, reports template drift, and restarts the gateway. The installer
  now records which template version seeded the user-owned persona/config
  (`~/.hermes/.template-seeds`); `scripts/template-drift.sh` reports — and
  never merges — upstream template changes, acknowledged with `--ack`.
- Release methodology docs: "Upgrade notes" changelog convention and user
  update path in `docs/releases.md` and `docs/getting-started.md`; placement
  rule in `CONTRIBUTING.md` (behavioral guardrails live in skills, which
  propagate on update; voice/personal context lives in the copy-once
  persona/config seeds).

### Upgrade notes

- The persona template gained verified-state reporting and queued-task
  rules this cycle (see *Changed*). Existing installs: run
  `bash scripts/template-drift.sh`, review the printed diff against
  `~/.hermes/SOUL.md`, port what applies, then acknowledge with `--ack`.

### Changed

- Verified-state reporting: the persona and worker skill now require every
  status claim (edited, committed, pushed, PR open, merged, deployed) to be
  derived from a fresh command check at message time, with file paths cited
  as written — a PR the assistant opened is reported as "open, ready for
  review", never "merged" (the user merges).
- Lane discipline for queued work: the producer skill now forbids dequeuing
  a ready task to implement it inline. A request to hurry a queued task
  means report state and expected worker pickup; `hermes kanban remove` is
  reserved for explicit user-requested cancellation.

## [0.1.0] - 2026-07-21

Initial open-source release.

### Security

- Pin `.cc-verify` before model stages and refuse modified verification gates.
- Block pushes of inherited private history and broaden publication/secret scans.
- Validate worker identifiers and require exact runner executable identities.

### Added

- Open-source readiness audit and publication gate.
- Reproducible local development commands.
- GitHub CI and tagged-release workflows.
- Validated public provider and custom coding-flow configuration.
- `classic`, `balanced`, `quality`, and `local` coding-flow presets.
- Multi-stage Claude Code/Codex runner with artifact handoffs and deterministic verification.
- Ristretto CLI, provider doctor, and safe first-stage installer/uninstaller.
- User-owned instance and repository configuration with environment overrides.
- Idempotent Hermes asset/worker/cron installer with explicit service opt-in.
- Private/public repository split and history-free public snapshot exporter.
- Getting-started guide and illustrated README.
