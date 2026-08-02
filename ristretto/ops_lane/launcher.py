"""Build the per-turn MCP config and the headless Claude Code argv.

The phone lane is interactive-gated, NOT the unattended durable-dev profile: it
relies on --permission-prompt-tool so unmatched tool calls reach your phone. It
also loads a strict settings file and excludes your permissive desktop settings
so the phone can never inherit a broad allow."""
from __future__ import annotations

import json
from pathlib import Path


def build_mcp_config(
    broker_python: str,
    session_id: str,
    spool_dir: Path,
    timeout_s: float,
    broker_module: str = "ristretto.ops_lane.approval_broker",
) -> dict:
    """MCP config registering the approval broker, stamped with the owning chat.

    Claude passes no cwd to the permission tool, so the owning chat id travels
    to the broker through RISTRETTO_OPS_SESSION in the server's env."""
    return {
        "mcpServers": {
            "approve": {
                "type": "stdio",
                "command": broker_python,
                "args": ["-m", broker_module],
                "env": {
                    "RISTRETTO_OPS_SESSION": str(session_id),
                    "RISTRETTO_OPS_SPOOL": str(spool_dir),
                    "RISTRETTO_OPS_APPROVAL_TIMEOUT": str(timeout_s),
                },
            }
        }
    }


def write_mcp_config(
    directory: Path,
    broker_python: str,
    session_id: str,
    spool_dir: Path,
    timeout_s: float,
) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"approve-{session_id}.mcp.json"
    path.write_text(
        json.dumps(build_mcp_config(broker_python, session_id, spool_dir, timeout_s))
    )
    return path


def build_claude_argv(
    prompt: str,
    mcp_config_path: Path,
    *,
    resume_session_id: str | None = None,
    settings_path: Path | None = None,
    setting_sources: str = "all",
    strict_mcp: bool = False,
    tool: str = "mcp__approve__ask",
    claude_bin: str = "claude",
) -> list[str]:
    """Argv for one conversational turn.

    --output-format json gives us Claude's session_id (to resume) + reply text.
    --resume continues the conversation. --settings layers the always-block deny
    file on top of the loaded config (deny beats allow). setting_sources="all"
    loads your full desktop config for parity; strict_mcp restricts to only the
    approval server when set."""
    argv = [claude_bin, "-p", "--output-format", "json"]
    if resume_session_id:
        argv += ["--resume", resume_session_id]
    argv += ["--mcp-config", str(mcp_config_path)]
    if strict_mcp:
        argv += ["--strict-mcp-config"]
    if setting_sources and setting_sources != "all":
        # Omitted entirely for "all" so Claude loads user+project+local (parity).
        argv += ["--setting-sources", setting_sources]
    if settings_path is not None:
        argv += ["--settings", str(settings_path)]
    argv += ["--permission-prompt-tool", tool, prompt]
    return argv
