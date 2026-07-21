# Changelog

All notable changes to Ristretto will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and releases use [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

## [0.1.0] - TBD

- Initial open-source release.
