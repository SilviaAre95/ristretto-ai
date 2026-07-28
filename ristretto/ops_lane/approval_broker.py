"""Approval broker: the MCP tool Claude Code calls via --permission-prompt-tool.

It NEVER decides policy. It records the pending action to the spool, blocks for
the daemon's decision (your Telegram tap), and returns Claude Code's permission
result. Timeout parks the action as a deny (fail closed).

Contract (verified against real Claude Code 2.1.x):
- The tool is called with {"tool_name", "input": {...}, "tool_use_id"} — the
  field is `input`, and Claude passes NO cwd. The owning chat is therefore
  stamped at launch via the RISTRETTO_OPS_SESSION env var.
- The result MUST be a single text block whose text is JSON:
  {"behavior": "allow", "updatedInput": <input>} or
  {"behavior": "deny", "message": "<reason>"}.
- FastMCP adds a `structuredContent` field that Claude rejects, so this uses the
  low-level MCP server to return exactly one TextContent.
"""
from __future__ import annotations

import os
import uuid

from .spool import Spool


def build_permission_result(
    behavior: str, *, updated_input: dict | None = None, message: str = ""
) -> dict:
    """Build the exact JSON Claude Code expects back from the permission tool."""
    if behavior == "allow":
        return {"behavior": "allow", "updatedInput": updated_input or {}}
    return {"behavior": "deny", "message": message or "Denied."}


def decide(payload: dict, spool: Spool, timeout_s: float) -> dict:
    """Record the pending action, block for the daemon's decision, map to result."""
    request_id = str(payload.get("tool_use_id") or uuid.uuid4().hex)
    spool.write_request(request_id, payload)
    result = spool.await_decision(request_id, timeout_s=timeout_s)
    if result is None:
        return build_permission_result(
            "deny", message="No response before timeout; parked (deny)."
        )
    if result.get("permissionDecision") == "allow":
        return build_permission_result("allow", updated_input=payload.get("input") or {})
    return build_permission_result(
        "deny", message=result.get("reason", "Denied from Telegram.")
    )


def main() -> None:  # pragma: no cover - exercised as a live MCP server
    import json

    import anyio
    import mcp.types as types
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server

    from .config import load_ops_config

    cfg = load_ops_config(os.environ)
    spool = Spool(cfg.spool_dir)
    timeout_s = cfg.approval_timeout_s
    session = os.environ.get("RISTRETTO_OPS_SESSION", "")

    server = Server("approve")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="ask",
                description="Gate a tool call behind a Telegram Approve/Deny tap.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tool_name": {"type": "string"},
                        "input": {"type": "object"},
                        "tool_use_id": {"type": "string"},
                    },
                },
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        payload = {
            "tool_name": arguments.get("tool_name", ""),
            "input": arguments.get("input") or {},
            "tool_use_id": arguments.get("tool_use_id", ""),
            "session": session,
        }
        # Blocking spool wait runs off the event loop so the server stays responsive.
        result = await anyio.to_thread.run_sync(decide, payload, spool, timeout_s)
        return [types.TextContent(type="text", text=json.dumps(result))]

    async def run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(run)


if __name__ == "__main__":
    main()
