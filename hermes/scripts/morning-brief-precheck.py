#!/usr/bin/env python3
"""Emit a Linear-board delta for the morning brief, or exactly NO_CHANGES."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


DONE_TYPES = {"completed", "canceled", "cancelled"}


def parse_args() -> argparse.Namespace:
    default_home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--state-file",
        type=Path,
        default=default_home / "state" / "morning-brief-board.json",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--fixture", type=Path, help=argparse.SUPPRESS)
    return parser.parse_args()


def unwrap_mcp_result(raw: str) -> dict[str, Any]:
    data: Any = json.loads(raw)
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(str(data["error"]))
    if isinstance(data, dict) and "result" in data:
        data = data["result"]
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise RuntimeError("Linear list_issues returned an unexpected response")
    if "error" in data:
        raise RuntimeError(str(data["error"]))
    return data


def configured_team() -> str:
    if os.environ.get("RISTRETTO_LINEAR_TEAM"):
        return os.environ["RISTRETTO_LINEAR_TEAM"]
    result = subprocess.run(
        ["ristretto", "instance", "get", "linear_team"],
        text=True,
        capture_output=True,
        check=False,
    )
    team = result.stdout.strip()
    if result.returncode != 0 or not team:
        raise RuntimeError(
            "Linear team is not configured; run ristretto configure --linear-team <KEY>"
        )
    return team


def fetch_issues() -> list[dict[str, Any]]:
    # Imported lazily so fixture tests do not need the Hermes runtime.
    from tools.mcp_tool import discover_mcp_tools
    from tools.registry import registry

    discover_mcp_tools()
    entry = registry.get_entry("mcp_linear_list_issues")
    if entry is None:
        raise RuntimeError("Linear list_issues tool is unavailable")
    data = unwrap_mcp_result(
        entry.handler(
            {
                "team": configured_team(),
                "limit": 250,
                "orderBy": "updatedAt",
                "includeArchived": False,
            }
        )
    )
    if data.get("hasNextPage"):
        raise RuntimeError("Linear board exceeds the 250-issue snapshot limit")
    issues = data.get("issues")
    if not isinstance(issues, list):
        raise RuntimeError("Linear list_issues response has no issues list")
    return [item for item in issues if isinstance(item, dict)]


def load_fixture(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("issues")
    if not isinstance(data, list):
        raise RuntimeError("fixture must be an issue list or an object with issues")
    return [item for item in data if isinstance(item, dict)]


def issue_key(issue: dict[str, Any]) -> str:
    for value in (issue.get("identifier"), issue.get("url"), issue.get("gitBranchName")):
        match = re.search(r"\b[A-Z][A-Z0-9]+-\d+\b", str(value or ""), re.IGNORECASE)
        if match:
            return match.group(0).upper()
    return str(issue.get("id") or "unknown")


def clean(value: Any) -> str:
    return " ".join(str(value or "").replace("|", "/").split())


def normalize(issue: dict[str, Any]) -> dict[str, Any] | None:
    status_type = clean(issue.get("statusType")).lower()
    if issue.get("archivedAt") or status_type in DONE_TYPES:
        return None
    priority = issue.get("priority") or {}
    if not isinstance(priority, dict):
        priority = {}
    return {
        "key": issue_key(issue),
        "title": clean(issue.get("title")),
        "project": clean(issue.get("project")) or "No project",
        "status": clean(issue.get("status")) or status_type or "Unknown",
        "status_type": status_type,
        "priority": int(priority.get("value") or 0),
        "priority_name": clean(priority.get("name")) or "No priority",
        "updated_at": clean(issue.get("updatedAt")),
    }


def snapshot(issues: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    normalized = [item for issue in issues if (item := normalize(issue)) is not None]
    return {item["key"]: item for item in sorted(normalized, key=lambda item: item["key"])}


def read_previous(path: Path) -> dict[str, dict[str, Any]] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"invalid snapshot state: {path}")
    return data


def write_snapshot(path: Path, data: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def issue_line(issue: dict[str, Any]) -> str:
    return (
        f"- {issue['key']} | {issue['project']} | {issue['priority_name']} | "
        f"{issue['status']} | {issue['title']}"
    )


def render_delta(
    previous: dict[str, dict[str, Any]] | None,
    current: dict[str, dict[str, Any]],
) -> str:
    if previous == current:
        return "NO_CHANGES"

    if previous is None:
        delta_lines = [f"- Initial snapshot: {len(current)} open issues"]
    else:
        added = sorted(set(current) - set(previous))
        removed = sorted(set(previous) - set(current))
        changed = sorted(
            key for key in set(current) & set(previous) if current[key] != previous[key]
        )
        delta_lines = []
        delta_lines.extend(f"- Added: {issue_line(current[key])[2:]}" for key in added)
        delta_lines.extend(f"- Updated: {issue_line(current[key])[2:]}" for key in changed)
        delta_lines.extend(f"- Left open board: {issue_line(previous[key])[2:]}" for key in removed)

    signal = [
        issue
        for issue in current.values()
        if issue["priority"] in {1, 2} or issue["status_type"] == "started"
    ]
    signal.sort(
        key=lambda issue: (
            0 if issue["status_type"] == "started" else 1,
            issue["priority"] or 9,
            issue["project"].lower(),
            issue["key"],
        )
    )
    signal_lines = [issue_line(issue) for issue in signal] or ["- None"]
    return "\n".join(
        [
            "CHANGES SINCE LAST BRIEF:",
            *delta_lines,
            "",
            "CURRENT URGENT, HIGH, OR IN-PROGRESS ISSUES:",
            *signal_lines,
        ]
    )


def run(args: argparse.Namespace) -> int:
    issues = load_fixture(args.fixture) if args.fixture else fetch_issues()
    current = snapshot(issues)
    previous = read_previous(args.state_file)
    output = render_delta(previous, current)
    write_snapshot(args.state_file, current)
    print(output)
    return 0


if __name__ == "__main__":
    try:
        exit_code = run(parse_args())
    except Exception as exc:
        print(f"morning-brief precheck failed: {exc}", file=sys.stderr)
        exit_code = 1
    # MCP discovery owns a background event loop that can take minutes to
    # drain. This process is single-purpose, so exit after flushing output.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)
