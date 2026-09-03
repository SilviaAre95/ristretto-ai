"""Nemo's tools, exposed to its own agent loop over MCP.

The loop is `claude -p` driven with this as an MCP server — the same mechanism
the approval broker uses, so no new auth and no new dependency. This is the
one place Nemo's capabilities are declared; the loop grants a subset of them
per surface.

v1 holds a single read-only tool: the fleet. It exists to prove the loop
mechanics — can we drive claude with our tools and get a reliable call —
before the mutating tools (launch, approve) arrive behind the approval gate.

Two contract facts, learned the hard way in broker.py and kept here:
the server must advertise its tools capability explicitly, and every reply is
exactly one TextContent whose text is JSON. FastMCP's structuredContent is
rejected by Claude Code.
"""

from __future__ import annotations

import json
from typing import Any


def fleet_status() -> dict[str, Any]:
    """A compact summary of every run Nemo knows about.

    Read-only and cheap: assembled from the board and the event log, the same
    source the dashboard uses. Deliberately small — a tool result that fills
    the context window is a tool nobody can afford to call.
    """
    try:
        from ..dash import data

        runs = data.fleet()
    except Exception as exc:  # noqa: BLE001 - a tool must answer, not raise
        return {"error": f"could not read the fleet: {exc}", "runs": []}

    summary = [
        {
            "issue": r.issue_key or r.task_id,
            "project": r.project,
            "status": r.status,
            "health": r.health,
            "stage": r.stage,
        }
        for r in runs[:20]
    ]
    live = [r for r in summary if r["health"] in ("running", "stalled")]
    return {
        "total": len(runs),
        "live": len(live),
        "runs": summary,
    }


# The tool table: name -> (description, zero-arg callable). v1 is read-only.
TOOLS: dict[str, tuple[str, Any]] = {
    "fleet_status": (
        "The current state of every run: what is live, stalled, blocked or done.",
        fleet_status,
    ),
}


def main() -> None:  # pragma: no cover - exercised as a live MCP server
    import anyio
    import mcp.types as types
    from mcp.server.lowlevel import Server, NotificationOptions
    from mcp.server.stdio import stdio_server

    server = Server("nemo-tools")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=name,
                description=desc,
                inputSchema={"type": "object", "properties": {}},
            )
            for name, (desc, _fn) in TOOLS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        entry = TOOLS.get(name)
        if entry is None:
            payload = {"error": f"unknown tool {name}"}
        else:
            _desc, fn = entry
            payload = await anyio.to_thread.run_sync(fn)
        return [types.TextContent(type="text", text=json.dumps(payload, default=str))]

    async def serve() -> None:
        options = server.create_initialization_options(
            notification_options=NotificationOptions(tools_changed=False),
            experimental_capabilities={},
        )
        async with stdio_server() as (read, write):
            await server.run(read, write, options)

    anyio.run(serve)


if __name__ == "__main__":  # pragma: no cover
    main()
