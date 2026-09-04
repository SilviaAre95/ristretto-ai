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


def search_memory(query: str = "") -> dict[str, Any]:
    """Find notes in the user's vault whose summary or content matches."""
    from . import vault
    return vault.search(query)


def read_note(path: str = "") -> dict[str, Any]:
    """Read one vault note in full, by the path search_memory returned."""
    from . import vault
    return vault.read(path)


def propose_merge(project: str = "", issue: str = "") -> dict[str, Any]:
    """Propose merging an issue's PR — a gated action, so it does NOT merge.

    Merging to main is one of the two dangerous, human-approved actions (deploy
    is the other). Nemo cannot merge on its own say-so: this finds the open PR
    for the issue and records a pending approval naming that exact PR, which
    the user confirms on the dashboard or with !ris-approve. The PR number is
    fixed now, so what gets merged cannot change between proposal and approval.
    """
    from ..dash.launch import branch_for
    from ..config import load_config, repository_path
    from .. import actions
    import subprocess

    if not project or not issue:
        return {"ok": False, "message": "I need the project and the issue key to find the PR."}
    issue = issue.upper()
    try:
        config, _ = load_config()
        repo = repository_path(config, project)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"I couldn't resolve {project}: {exc}"}

    branch = branch_for(issue)
    try:
        found = subprocess.run(
            ["gh", "pr", "list", "--head", branch, "--state", "open",
             "--json", "number,title,url", "--jq", ".[0]"],
            cwd=repo, capture_output=True, text=True, check=False, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "message": f"I couldn't reach GitHub: {exc}"}
    line = (found.stdout or "").strip()
    if not line:
        return {"ok": False, "message": f"No open PR for {issue} (branch {branch}). Has the run finished?"}
    import json as _json
    pr = _json.loads(line)
    slug = _repo_slug(repo)
    record = actions.record_merge(issue, slug, pr["number"], branch, project=project)
    return {
        "ok": True,
        "message": (
            f"Queued PR #{pr['number']} ({pr.get('title','')}) for your approval. "
            f"Approve it on the dashboard or reply !ris-approve — I won't merge until you do."
        ),
        "pr": pr["number"],
        "approval_id": record["id"],
    }


def _repo_slug(repo_path) -> str:
    """owner/name for `gh --repo`, from the repo's origin remote."""
    import subprocess
    try:
        out = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
            cwd=repo_path, capture_output=True, text=True, check=False, timeout=30,
        )
        return (out.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def launch_run(project: str = "", issue: str = "", flow: str = "tier1", unattended: bool = False) -> dict[str, Any]:
    """Start a supervised coding run — dev work, so it runs without a gate.

    Kicking off a run is dev work, not a dangerous action: it produces a pull
    request the user reviews before anything merges or deploys. So it executes
    directly, protected by launch.launch's own guards — a valid issue key, a
    committed verify gate (preflight), and a refusal when the fleet is already
    busy. The gates that matter come later, on merge and deploy.

    Nemo cannot guess which repository an issue key belongs to (projects share
    a Linear prefix), so it must pass the project explicitly. If it doesn't
    know, it should ask the user rather than launch the wrong repo.
    """
    from ..dash import launch as launcher

    if not project:
        return {"ok": False, "message": "which project? every issue key shares the same prefix, so I need the project name"}
    outcome = launcher.launch(project, issue.upper(), flow, actor="nemo", unattended=unattended)
    return {"ok": outcome.ok, "message": outcome.message, "task_id": outcome.task_id}


# The tool table. v1 is read-only: read the fleet, and read the second brain.
# Each entry is (description, callable, schema-properties).
TOOLS: dict[str, tuple[str, Any, dict]] = {
    "fleet_status": (
        "The current state of every run: what is live, stalled, blocked or done.",
        fleet_status,
        {},
    ),
    "search_memory": (
        "Search the user's Obsidian vault (their long-term memory) for notes on "
        "a project, decision or topic. Returns titles and summaries; call "
        "read_note for the full text of one.",
        search_memory,
        {"query": {"type": "string", "description": "what to look for"}},
    ),
    "read_note": (
        "Read one vault note in full, using a path from search_memory.",
        read_note,
        {"path": {"type": "string", "description": "the note's vault-relative path"}},
    ),
    "propose_merge": (
        "Propose merging an issue's PR. A gated action: it does NOT merge — it "
        "queues the exact PR for the user's approval. Requires project and issue.",
        propose_merge,
        {
            "project": {"type": "string", "description": "the configured project name"},
            "issue": {"type": "string", "description": "the issue key whose PR to merge"},
        },
    ),
    "launch_run": (
        "Start a supervised coding run on an issue. Dev work — it produces a PR "
        "the user reviews; it does not merge or deploy. Requires the project name "
        "(issue keys alone are ambiguous). Ask the user if unsure which project.",
        launch_run,
        {
            "project": {"type": "string", "description": "the configured project name, e.g. Kaffecard"},
            "issue": {"type": "string", "description": "the issue key, e.g. XARI-26"},
            "flow": {"type": "string", "description": "tier0-3 or classic; default tier1"},
            "unattended": {"type": "boolean", "description": "true for a run nobody will watch"},
        },
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
                inputSchema={"type": "object", "properties": props},
            )
            for name, (desc, _fn, props) in TOOLS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        entry = TOOLS.get(name)
        if entry is None:
            payload = {"error": f"unknown tool {name}"}
        else:
            _desc, fn, _props = entry
            payload = await anyio.to_thread.run_sync(lambda: fn(**(arguments or {})))
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
