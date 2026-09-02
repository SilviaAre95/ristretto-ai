"""Tell the user what happened, in the place they already look.

A dashboard you have to remember to open is a dashboard you stop opening —
which is how the last one died. So Slack is the doorbell and the dashboard is
the room: milestones arrive in a channel you already read, each carrying a
link into the fleet view.

Only milestones. A tier run emits a dozen events and eleven of them are
progress; notifying on all of them trains you to ignore the channel, which
costs more than sending nothing. Stage starts and passes stay in the log
where they belong, and the doorbell rings for outcomes and for trouble.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping

from . import events
from .config import ConfigError, instance_value, load_config

# What is worth interrupting someone for. Stage starts and passes are
# deliberately absent: a run emits six of each, and a channel that pings
# twelve times per task is a channel nobody reads.
MILESTONES = {
    "run.started",
    "run.ended",
    "stage.failed",
    "verify.red",
    "grader.failed",
    "pr.opened",
    "awaiting.approval",
    "preflight.failed",
    "control.stop",
}

ICON = {
    "run.started": "▶",
    "run.ended": "✓",
    "stage.failed": "✕",
    "verify.red": "✕",
    "grader.failed": "✕",
    "pr.opened": "→",
    "awaiting.approval": "?",
    "preflight.failed": "✕",
    "control.stop": "■",
}


def cursor_path(environ: Mapping[str, str] | None = None) -> Path:
    return events.state_home(environ) / "doorbell.cursor"


def read_cursor(path: Path | None = None) -> int:
    target = cursor_path() if path is None else path
    try:
        return int(target.read_text().strip())
    except (OSError, ValueError):
        return 0


def write_cursor(value: int, path: Path | None = None) -> None:
    target = cursor_path() if path is None else path
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(value))
    except OSError:
        pass


def since(cursor: int, limit: int = 200, path: Path | None = None) -> list[dict[str, Any]]:
    """Milestone events newer than the cursor, oldest first."""
    fresh = [
        item
        for item in events.read(limit=limit, path=path)
        if int(item.get("id") or 0) > cursor and item.get("kind") in MILESTONES
    ]
    return sorted(fresh, key=lambda item: int(item.get("id") or 0))


def brief(text: Any, limit: int = 150) -> str:
    """A notification has to be readable at a glance.

    Failure detail can be a wall of build output; the whole of it belongs on
    the task page the link points at, not in the channel.
    """
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def compose(event: Mapping[str, Any], base_url: str) -> str:
    """One line a person can act on, and a link to the rest."""
    kind = str(event.get("kind"))
    task = str(event.get("task_id"))
    issue = event.get("issue_key") or task
    payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    icon = ICON.get(kind, "·")

    if kind == "pr.opened":
        return f"{icon} {issue} — pull request ready\n{payload.get('url', '')}"
    if kind == "run.started":
        flow = payload.get("flow", "?")
        return f"{icon} {issue} — started on {flow}\n{base_url}/task/{task}"
    if kind == "run.ended":
        outcome = payload.get("outcome", "?")
        if outcome == "completed":
            return f"{icon} {issue} — finished\n{base_url}/task/{task}"
        return f"✕ {issue} — {outcome}\n{base_url}/task/{task}"
    if kind == "control.stop":
        return f"{icon} {issue} — stopped from the dashboard\n{base_url}/task/{task}"
    if kind == "awaiting.approval":
        # Say how to answer, and say DM: a reply in a channel is not
        # delivered to the bot unless it @mentions it, and a mention puts
        # the mention first so the command is never recognised. A DM is the
        # only form that reaches the command dispatcher.
        request_id = str(payload.get("id", "")).strip()
        answer = f" {request_id}" if request_id else ""
        how = f"!ris-approve{answer} · !ris-deny{answer} <reason>"
        return (
            f"{icon} {issue} — waiting on you: {brief(payload.get('what', 'approval'))}"
            f"\n{base_url}/task/{task}"
            f"\nOr DM me: {how}"
        )
    if kind == "preflight.failed":
        # Not a run, so there is no task page to link to — the repo cannot
        # host a loop at all, and the errors are the whole message.
        problems = payload.get("errors") or []
        detail = brief("; ".join(str(p) for p in problems[:2]) or "not loop-capable")
        repo = Path(str(payload.get("repo", ""))).name or task.replace("preflight-", "")
        return f"{icon} {repo} — cannot run a loop: {detail}"

    reason = brief(
        payload.get("reason") or payload.get("detail") or payload.get("grader") or kind
    )
    stage = f" at {event['stage']}" if event.get("stage") else ""
    return f"{icon} {issue} — failed{stage}: {reason}\n{base_url}/task/{task}"


def deliver(text: str, channel: str, timeout: int = 60) -> bool:
    """Send one message. A failed send is reported, never retried into a loop."""
    try:
        result = subprocess.run(
            ["hermes", "send", "-t", f"slack:{channel}", text],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env={**_env(), "HERMES_HOME": str(Path.home() / ".hermes")},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"doorbell: send failed: {exc}")
        return False
    if result.returncode != 0:
        print(f"doorbell: send failed: {(result.stderr or '').strip()[:200]}")
        return False
    return True


def _env() -> dict[str, str]:
    import os

    return dict(os.environ)


def ring(base_url: str, channel: str, dry_run: bool = False, path: Path | None = None) -> int:
    """Deliver every milestone since the last one. Returns how many were sent."""
    cursor = read_cursor()
    fresh = since(cursor, path=path)
    if not fresh:
        return 0
    sent = 0
    highest = cursor
    for event in fresh:
        text = compose(event, base_url)
        if dry_run:
            print(text.replace("\n", " | "))
            sent += 1
        elif deliver(text, channel):
            sent += 1
        else:
            # Stop at the first failure so the cursor does not skip past
            # milestones that were never delivered.
            break
        highest = max(highest, int(event.get("id") or 0))
    if not dry_run:
        write_cursor(highest)
    return sent


def watch(base_url: str, channel: str, interval: int = 20) -> int:
    print(f"doorbell: watching for milestones, posting to slack:{channel}")
    while True:
        try:
            ring(base_url, channel)
        except Exception as exc:  # noqa: BLE001 - a notifier must not die
            print(f"doorbell: {exc}")
        time.sleep(interval)


def resolve_channel(config: Mapping[str, Any]) -> str:
    for key in ("slack_alerts_channel", "slack_home_channel"):
        try:
            return instance_value(config, key)
        except ConfigError:
            continue
    raise ConfigError("no Slack channel configured for alerts or home")
