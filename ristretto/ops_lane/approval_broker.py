"""Approval broker: the MCP tool Claude Code calls via --permission-prompt-tool.

It NEVER decides policy. It records the pending action to the spool, blocks for
the daemon's decision (your tap), and maps the result into Claude Code's
PreToolUse hook envelope. Timeout parks the action as a deny (fail closed)."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from .spool import Spool


def build_hook_output(decision: str, reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }


def decide(payload: dict, spool: Spool, timeout_s: float) -> dict:
    request_id = str(payload.get("tool_use_id") or uuid.uuid4().hex)
    spool.write_request(request_id, payload)
    result = spool.await_decision(request_id, timeout_s=timeout_s)
    if result is None:
        return build_hook_output("deny", "No response before timeout; parked (deny).")
    decision = result.get("permissionDecision", "deny")
    reason = result.get("reason", "Relayed from Telegram.")
    return build_hook_output(decision, reason)


def main() -> None:  # pragma: no cover - exercised as a live MCP server
    from mcp.server.fastmcp import FastMCP

    spool = Spool(Path(os.environ.get("RISTRETTO_OPS_SPOOL", "~/.hermes/ops-spool")).expanduser())
    timeout_s = float(os.environ.get("RISTRETTO_OPS_APPROVAL_TIMEOUT", "600"))
    server = FastMCP("approve")

    @server.tool()
    def ask(
        tool_name: str = "",
        tool_input: dict | None = None,
        cwd: str = "",
        permission_mode: str = "",
        session_id: str = "",
        tool_use_id: str = "",
    ) -> str:
        import json

        payload = {
            "tool_name": tool_name,
            "tool_input": tool_input or {},
            "cwd": cwd,
            "permission_mode": permission_mode,
            "session_id": session_id,
            "tool_use_id": tool_use_id,
        }
        return json.dumps(decide(payload, spool, timeout_s))

    server.run()


if __name__ == "__main__":
    main()
