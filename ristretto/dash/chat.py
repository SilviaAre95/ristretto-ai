"""Ask Ris about the fleet, from the fleet view.

Ris already exists — persona, memory, tools — and answers on Slack and the
CLI. This is the same agent reached from the dashboard, with two deliberate
narrowings.

**Tools are restricted.** Ris normally has terminal, file, code execution and
delegation. Exposed unmodified on a page with no login, a chat box is remote
code execution over HTTP for anyone on the tailnet: asked to run a shell
command, the unrestricted agent runs it and reports the output. Here it is
invoked with a minimal toolset and answers from context instead. Widening
this is a one-line change to TOOLSETS, and should be a deliberate one.

**Context is injected rather than fetched.** The dashboard already knows the
fleet, so it hands Ris a summary instead of granting the tools to go and
look. Fewer capabilities, better answers, and the question "why did XARI-33
stall" works without the user naming a task id.
"""

from __future__ import annotations

import subprocess
from typing import NamedTuple

from .. import events
from . import data

# Deliberately minimal. Not terminal, file, code_execution, browser,
# delegation or cronjob — see the module docstring.
TOOLSETS = "memory"
TIMEOUT_SECONDS = 180
MAX_MESSAGE = 4000

BRIEF = """You are answering from the Ristretto dashboard, where the user is
watching agents work. Below is the current fleet, already gathered for you —
use it to answer rather than looking anything up. Be brief and concrete. If
the fleet does not contain the answer, say so plainly instead of guessing.

--- fleet ---
{fleet}
--- end fleet ---

{question}"""


class Reply(NamedTuple):
    ok: bool
    text: str


def fleet_context(limit: int = 12) -> str:
    """A compact picture of what is running and what recently happened."""
    runs, _ = data.recent(data.fleet())
    if not runs:
        return "No runs in the last 7 days."
    lines = []
    for run in runs[:limit]:
        parts = [
            f"{run.issue_key or run.task_id} ({run.task_id})",
            f"project={run.project}",
            f"status={run.status}",
            f"health={run.health}",
        ]
        if run.stage:
            parts.append(f"stage={run.stage}")
        if run.elapsed is not None:
            parts.append(f"elapsed={data.humanise(run.elapsed)}")
        parts.append(f"last_signal={data.ago(run.last_signal_at)}")
        if run.failure:
            parts.append(f"failure={run.failure}")
        lines.append("- " + "  ".join(parts))
        for event in run.events[:4]:
            # format_line already renders the payload; the task id is dropped
            # because the run it belongs to is named on the line above.
            rendered = events.format_line(event).split("  ", 2)[-1]
            lines.append(f"    {rendered}"[:280])
    return "\n".join(lines)


def ask(question: str, timeout: int = TIMEOUT_SECONDS) -> Reply:
    """Put a question to Ris with the fleet as context and no dangerous tools."""
    question = (question or "").strip()
    if not question:
        return Reply(False, "Ask something first.")
    if len(question) > MAX_MESSAGE:
        return Reply(False, f"That is longer than {MAX_MESSAGE} characters.")
    prompt = BRIEF.format(fleet=fleet_context(), question=question)
    try:
        result = subprocess.run(
            ["hermes", "-z", prompt, "-t", TOOLSETS],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return Reply(False, f"Ris did not answer within {timeout}s.")
    except (OSError, subprocess.SubprocessError) as exc:
        return Reply(False, f"Could not reach Ris: {exc}")
    text = (result.stdout or "").strip()
    if result.returncode != 0 and not text:
        detail = (result.stderr or "").strip().splitlines()
        return Reply(False, " / ".join(detail[-2:]) or f"Ris exited {result.returncode}")
    return Reply(True, text or "(no answer)")
