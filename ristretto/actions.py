"""Gated actions — the dangerous things a human approves before they happen.

Dev work runs freely; this is the other half. Merging a PR to main and
deploying to production are the actions that touch reality, so they never run
on a model's say-so. They are *proposed* — recorded as a pending approval that
names the exact target — and they *execute only when a human approves*.

The design is "execute on approve": the human's click on the dashboard, or
their !ris-approve in Slack, is what fires the action, in the same call that
records the decision. No watcher, no queue. The approval store already gives
two surfaces, first-decision-wins and fail-closed; this adds the single step
of doing the thing once the allow lands.

Why the exact target is fixed at propose time: a conversational "merge it"
could be answered a minute later, and the model must not be able to change
which PR gets merged in between. The approval record pins the PR number; the
executor reads it, not the model.

approvals.py stays pure — it decides nothing and executes nothing. This module
is where policy and side effects live.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

from . import approvals

# Actions this module knows how to execute. An approval whose tool_name is not
# here is a plain permission prompt, decided but never "run".
MERGE = "merge_pr"


def record_merge(
    issue: str,
    repo_slug: str,
    pr_number: int,
    branch: str,
    *,
    project: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    """Propose a merge. Creates a gated approval naming the exact PR.

    Does not merge. Returns the approval so the surfaces can show it.
    """
    request_id = f"merge-{repo_slug}-{pr_number}"
    return approvals.request(
        request_id,
        f"merge-{issue}",
        MERGE,
        {
            "kind": "merge",
            "repo": repo_slug,
            "pr": int(pr_number),
            "branch": branch,
            "project": project,
            "issue": issue,
        },
        issue_key=issue,
        stage="merge",
        path=path,
    )


def answer(
    request_id: str,
    verdict: str,
    *,
    actor: str,
    reason: str = "",
    path: Path | None = None,
) -> tuple[bool, str]:
    """Decide an approval, and if it is a winning allow of an action, run it.

    This is what the gate surfaces call instead of approvals.decide directly,
    so the action fires exactly once, from whichever surface won the race.
    """
    won, message = approvals.decide(request_id, verdict, actor=actor, reason=reason, path=path)
    if not won or approvals.decision_of(verdict) != approvals.ALLOW:
        return won, message

    record = approvals.get(request_id, path=path)
    if not record or record.get("tool_name") != MERGE:
        return won, message  # a plain permission, nothing to execute

    ok, detail = _execute_merge(record.get("tool_input") or {})
    # The outcome belongs on the record: an approval that was allowed but whose
    # merge failed is not the same as one that merged.
    _note_result(request_id, ok, detail, path=path)
    return won, f"{message} — {detail}"


def _execute_merge(action: Mapping[str, Any]) -> tuple[bool, str]:
    """Merge the PR the approval named. Never the model's idea of the PR."""
    repo = str(action.get("repo") or "")
    pr = action.get("pr")
    if not repo or not pr:
        return False, "merge approval missing repo or pr"
    try:
        result = subprocess.run(
            ["gh", "pr", "merge", str(pr), "--repo", repo, "--squash", "--delete-branch"],
            capture_output=True, text=True, check=False, timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"merge did not run: {exc}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        return False, f"merge failed: {' / '.join(detail[-2:]) or 'no detail'}"
    return True, f"merged PR #{pr}"


def _note_result(request_id: str, ok: bool, detail: str, path: Path | None = None) -> None:
    """Append the execution outcome to the approval's reason, best effort."""
    try:
        with approvals.connect(path) as connection:
            connection.execute(
                "UPDATE approvals SET reason = COALESCE(reason,'') || ? WHERE id = ?",
                (f" [{'done' if ok else 'FAILED'}: {detail[:200]}]", request_id),
            )
    except Exception:  # noqa: BLE001 - recording the note must not raise
        pass
