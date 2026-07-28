"""Ops-lane runtime configuration, read from the environment with safe defaults.

Secrets (bot token, allowed user IDs) are read elsewhere at point of use; this
holds only non-secret paths and tunables."""
from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# Shipped default phone-lane guardrail (deny dangerous, allow read-only,
# everything else falls through to a Telegram Approve/Deny).
DEFAULT_STRICT_SETTINGS = Path(__file__).resolve().parent / "phone_settings.json"


@dataclass
class OpsConfig:
    spool_dir: Path
    audit_path: Path
    approval_timeout_s: float
    slack_summary_channel_env: str
    poll_timeout_s: int
    claude_bin: str
    broker_python: str
    strict_settings_path: Path
    setting_sources: str
    strict_mcp: bool
    root_dir: Path
    sessions_path: Path


def load_ops_config(environ: Mapping[str, str]) -> OpsConfig:
    def path_of(key: str, default: str) -> Path:
        return Path(environ.get(key, default)).expanduser()

    return OpsConfig(
        spool_dir=path_of("RISTRETTO_OPS_SPOOL", "~/.hermes/ops-spool"),
        audit_path=path_of("RISTRETTO_OPS_AUDIT", "~/.hermes/logs/ops-audit.log"),
        approval_timeout_s=float(environ.get("RISTRETTO_OPS_APPROVAL_TIMEOUT", "600")),
        slack_summary_channel_env=environ.get(
            "RISTRETTO_OPS_SLACK_CHANNEL_ENV", "SLACK_HOME_CHANNEL"
        ),
        poll_timeout_s=int(environ.get("RISTRETTO_OPS_POLL_TIMEOUT", "25")),
        claude_bin=environ.get("RISTRETTO_OPS_CLAUDE_BIN", "claude"),
        broker_python=environ.get("RISTRETTO_OPS_BROKER_PYTHON", sys.executable),
        strict_settings_path=Path(
            environ.get("RISTRETTO_OPS_SETTINGS", str(DEFAULT_STRICT_SETTINGS))
        ).expanduser(),
        # Which of Claude Code's settings files to honor. "all" loads your full
        # desktop config (MCP tools, commands, agents, allow rules) for parity;
        # the strict deny file is layered on top as an always-block override
        # (deny beats allow). Set to "project" to exclude your desktop settings.
        setting_sources=environ.get("RISTRETTO_OPS_SETTING_SOURCES", "all"),
        # False (default) loads your normal MCP servers (Linear, etc.) alongside
        # the approval server, for full desktop parity. Set
        # RISTRETTO_OPS_STRICT_MCP=1 to restrict to only the approval server.
        strict_mcp=environ.get("RISTRETTO_OPS_STRICT_MCP", "0") == "1",
        # Working root every session opens in — you roam and create repos under
        # it. Set RISTRETTO_OPS_ROOT to narrow it (e.g. ~/ventures/code).
        root_dir=path_of("RISTRETTO_OPS_ROOT", "~"),
        # Where per-chat conversation ids are persisted so a daemon restart
        # resumes the same conversation instead of starting over.
        sessions_path=path_of("RISTRETTO_OPS_SESSIONS", "~/.hermes/ops-sessions.json"),
    )
