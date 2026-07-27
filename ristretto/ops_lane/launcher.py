"""Build the per-session MCP config and the headless Claude Code argv.

The launcher does NOT set --permission-mode acceptEdits (that is the unattended
Slack durable-dev profile). This lane relies on the permission-prompt tool so
`ask`/unmatched calls reach your phone; settings deny/allow resolve locally."""
from __future__ import annotations

import json
from pathlib import Path


def build_mcp_config(
    broker_python: str, broker_module: str = "ristretto.ops_lane.approval_broker"
) -> dict:
    return {
        "mcpServers": {
            "approve": {
                "type": "stdio",
                "command": broker_python,
                "args": ["-m", broker_module],
            }
        }
    }


def write_mcp_config(directory: Path, broker_python: str) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "approve.mcp.json"
    path.write_text(json.dumps(build_mcp_config(broker_python)))
    return path


def build_claude_argv(
    prompt: str,
    mcp_config_path: Path,
    tool: str = "mcp__approve__ask",
    claude_bin: str = "claude",
) -> list[str]:
    return [
        claude_bin,
        "-p",
        "--mcp-config",
        str(mcp_config_path),
        "--permission-prompt-tool",
        tool,
        prompt,
    ]
