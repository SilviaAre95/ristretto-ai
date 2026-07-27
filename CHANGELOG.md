# Changelog

All notable changes to Ristretto will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and releases use [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
