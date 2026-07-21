# Development Environment

Ristretto is primarily configuration, skills, shell scripts, and a small
Python precheck around the Hermes Agent runtime. Development should not require
access to the maintainer's live Slack or Linear accounts.

## Supported baseline

- macOS for the live `launchd` service path
- Python 3.11
- Bash 3.2 or newer
- Git
- Hermes Agent 0.18.x for live integration checks
- Optional: Ollama, Claude Code, Codex CLI, GitHub CLI

## Bootstrap

```bash
make setup
source .venv/bin/activate
make check
```

`make setup` creates a repository-local virtual environment and installs the
editable Ristretto CLI plus development dependencies. Repeat runs reuse the
venv's build tools and work offline once dependencies are present. Set
`RISTRETTO_UPGRADE_PIP=1` only when an explicit pip upgrade is wanted. Setup
does not edit `~/.hermes`, install a background service, log into a provider,
or copy secrets. In a checkout that contains the known private-history root it
also sets the repository-local `core.hooksPath` to `.githooks`; fresh public
exports do not contain that sentinel and are left unchanged.

## Commands

| Command | Purpose |
|---|---|
| `make test` | Run the deterministic shell test suites. |
| `make check` | Run tests, parse config files, check diffs, and scan tracked files for token-shaped secrets. |
| `make public-check` | Reject tracked runtime state, private paths, Slack IDs, and operational history. |
| `make install-push-guard` | Reinstall the private-history pre-push guard for this checkout. |
| `make doctor` | Check the developer's live Hermes installation and gateway. |
| `make install-hermes` | Safely add public Ristretto assets to an existing Hermes installation. |

CLI-specific checks:

```bash
ristretto validate
ristretto flow list
ristretto flow show balanced
ristretto doctor
```

## Live integration setup

Live integration is optional and machine-local. Copy only the variables needed
from `hermes/.env.example` into `~/.hermes/.env`; never place the resulting file
inside this repository. Configure non-secret instance settings with
`ristretto configure`, then use `make install-hermes`.

`make install` is deliberately limited to a CLI symlink and a user-owned copy
of the generic public configuration. It must not install the maintainer's Slack
channels, Linear team, repository paths, models, schedules, personal vault
locations, Hermes configuration, or background service.
