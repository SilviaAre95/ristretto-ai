"""Ops-lane runtime configuration, read from the environment with safe defaults.

Secrets (bot token, allowed user IDs) are read elsewhere at point of use; this
holds only non-secret paths and tunables."""
from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass
class OpsConfig:
    spool_dir: Path
    audit_path: Path
    approval_timeout_s: float
    slack_summary_channel_env: str
    poll_timeout_s: int
    claude_bin: str
    broker_python: str


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
    )
