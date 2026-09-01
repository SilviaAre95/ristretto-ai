"""The permission tool Claude Code calls when a flow stage needs consent.

Wired in with `--permission-prompt-tool`. Claude Code stops, calls this over
stdio MCP, and waits for the JSON it returns. So this process is the gate: it
records the question, blocks until a human answers on whichever surface they
reach first, and relays the verdict back.

Contract, verified against real Claude Code 2.1.x and preserved from the
earlier Telegram-era broker because rediscovering it is expensive:

- The call arrives as {"tool_name", "input": {...}, "tool_use_id"}. The field
  is `input`, not `arguments`, and Claude passes NO cwd — so the owning task
  is stamped into the environment at launch instead.
- The reply MUST be exactly one text block whose text is JSON:
  {"behavior": "allow", "updatedInput": <input>} or
  {"behavior": "deny", "message": "<reason>"}.
- FastMCP appends a `structuredContent` field that Claude rejects outright,
  so this uses the low-level MCP server to return a single TextContent.

It decides nothing. Policy lives with the person being asked.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Mapping

from . import approvals

# The tool name Claude Code is pointed at. Changing it means changing the
# --permission-prompt-tool flag the runner passes.
TOOL_NAME = "approve"


def permission_result(
    behavior: str, *, updated_input: Mapping[str, Any] | None = None, message: str = ""
) -> dict[str, Any]:
    """Build the exact JSON Claude Code expects back."""
    if behavior == approvals.ALLOW:
        return {"behavior": "allow", "updatedInput": dict(updated_input or {})}
    return {"behavior": "deny", "message": message or "Denied."}


def decide(payload: Mapping[str, Any], *, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Record the question, wait for a human, and map the answer to a result."""
    env = os.environ if environ is None else environ
    request_id = str(payload.get("tool_use_id") or uuid.uuid4().hex)
    task_id = env.get("RISTRETTO_TASK_ID", "")
    if not task_id:
        # Without a task there is no card to show and no way to answer, so
        # blocking would hang the stage until it timed out anyway. Say why.
        return permission_result(
            approvals.DENY,
            message="no owning task: the flow did not stamp RISTRETTO_TASK_ID",
        )

    timeout = _timeout(env)
    approvals.request(
        request_id,
        task_id,
        str(payload.get("tool_name") or "unknown tool"),
        payload.get("input") if isinstance(payload.get("input"), Mapping) else {},
        issue_key=env.get("RISTRETTO_ISSUE_KEY") or None,
        stage=env.get("RISTRETTO_STAGE") or None,
        timeout_seconds=timeout,
    )
    decision, reason = approvals.await_decision(request_id, timeout_seconds=timeout)
    if decision == approvals.ALLOW:
        return permission_result(approvals.ALLOW, updated_input=payload.get("input") or {})
    return permission_result(approvals.DENY, message=reason or "Denied.")


def _timeout(env: Mapping[str, str]) -> int:
    raw = str(env.get("RISTRETTO_APPROVAL_TIMEOUT", "")).strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return approvals.DEFAULT_TIMEOUT_SECONDS


def main() -> None:  # pragma: no cover - exercised as a live MCP server
    import anyio
    import mcp.types as types
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server

    server = Server("ris-approve")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=TOOL_NAME,
                description="Ask the operator to approve a tool call.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tool_name": {"type": "string"},
                        "input": {"type": "object"},
                        "tool_use_id": {"type": "string"},
                    },
                    "required": ["tool_name", "input"],
                },
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        if name != TOOL_NAME:
            result = permission_result(approvals.DENY, message=f"unknown tool {name}")
        else:
            # The wait is a person walking to a phone, so it must not block
            # the event loop and starve the stdio transport.
            result = await anyio.to_thread.run_sync(lambda: decide(arguments))
        # Exactly one text block. A second block, or FastMCP's structuredContent,
        # and Claude Code rejects the response.
        return [types.TextContent(type="text", text=json.dumps(result))]

    async def serve() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(serve)


if __name__ == "__main__":  # pragma: no cover
    main()
