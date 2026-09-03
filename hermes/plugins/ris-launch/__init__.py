"""Start a run from Slack.

The whole point of the assistant is directing work when you are not at the
machine. Launching was possible from the dashboard and the CLI but not from
the one surface you actually have on the go, which is backwards. This closes
that.

No model sits in this path. Like the approval commands, the handler parses a
fixed shape and shells the CLI, which owns every guard — preflight, the busy
check, the branch derivation. A launch is deterministic; only *deciding* what
to launch wants an agent, and that is a later, larger piece.

`!ris-start XARI-42` — default flow, attended. `!ris-start XARI-42 tier1
unattended` — a full run nobody has to watch.
"""

from __future__ import annotations

import re
import shutil
import subprocess

# A launch shells `ristretto launch`, which creates a board task and dispatches
# it. That is fast, but not instant; give it room without holding a chat turn
# open forever.
TIMEOUT_SECONDS = 120

ISSUE_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,9}-\d{1,6}$")
# Only the flows Nemo actually defines. Anything else is a typo, and the CLI
# would reject it anyway — catching it here gives a clearer message.
FLOWS = {"classic", "tier0", "tier1", "tier2", "tier3"}


def _ristretto() -> str | None:
    return shutil.which("ristretto")


def start(raw_args: str = "") -> str:
    """Kick off a run. `<issue> [flow] [unattended] [project:<name>]`.

    The project is inferred by the CLI from the issue when it is unambiguous;
    an explicit `project:Kaffecard` overrides. Kept deliberately terse: this
    is typed one-handed on a phone.
    """
    binary = _ristretto()
    if not binary:
        return "ristretto is not on PATH for the gateway process."

    tokens = (raw_args or "").split()
    if not tokens:
        return "Which issue? e.g. !ris-start XARI-42 tier1 unattended"

    issue = None
    flow = "tier1"
    unattended = False
    project = None
    for tok in tokens:
        low = tok.lower()
        if tok.startswith("project:"):
            project = tok.split(":", 1)[1]
        elif ISSUE_KEY.fullmatch(tok):
            issue = tok.upper()
        elif low in FLOWS:
            flow = low
        elif low in ("unattended", "bg", "away"):
            unattended = True
        # anything else is ignored rather than rejected — chat clients append
        # their own trailing text, and a stray word must not block a launch.

    if issue is None:
        return f"No issue key in that. Expected something like XARI-42; got: {raw_args!r}"
    if project is None:
        return (
            f"I can't tell which project {issue} is in from Slack. "
            f"Add it: !ris-start {issue} {flow} project:<name>"
        )

    args = [binary, "launch", project, issue, "--flow", flow, "--actor", "slack"]
    if unattended:
        args.append("--unattended")
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=TIMEOUT_SECONDS
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"could not start the run: {exc}"
    return (result.stdout or result.stderr or "no response from the launcher").strip()


def register(ctx) -> None:
    ctx.register_command(
        "ris-start",
        handler=start,
        description="Start a supervised run: !ris-start <issue> [flow] [unattended] project:<name>",
        args_hint="<issue> [flow] [unattended] project:<name>",
    )
