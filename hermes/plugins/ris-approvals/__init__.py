"""Answer a blocked Ristretto flow from Slack.

A flow that needs permission stops and waits. The dashboard can answer it,
but the dashboard is a thing you have to go and open; Slack is already on the
phone in your hand, so the answer has to be possible there too.

The important property is that nothing here uses a model. The command handler
parses a fixed vocabulary and writes a decision, exactly like Hermes's own
`/approve` does for its dangerous commands. An approval gate whose verdict is
inferred by an agent — one that also reads issue text, code comments and web
pages while it works — is a gate that can be talked through. So the decision
path is deterministic and the agent is not in it.

`!ris-approve` rather than `/ris-approve`: Slack refuses native slash commands
inside threads, and threads are where these conversations happen.
"""

from __future__ import annotations

import shutil
import subprocess

# Long enough for a cold Python start, short enough that a wedged CLI does not
# hold a chat turn open.
TIMEOUT_SECONDS = 30


def _ristretto() -> str | None:
    return shutil.which("ristretto")


def _run(args: list[str]) -> tuple[int, str]:
    binary = _ristretto()
    if not binary:
        return 1, "ristretto is not on PATH for the gateway process."
    try:
        result = subprocess.run(
            [binary, "approvals", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"could not reach the approval store: {exc}"
    output = (result.stdout or result.stderr or "").strip()
    return result.returncode, output


def pending(_raw_args: str = "") -> str:
    _, output = _run(["pending"])
    return output or "nothing waiting on you"


def _decide(verdict: str, raw_args: str) -> str:
    """Answer, naming a request only when the operator did.

    With one request pending the id is optional — that is what makes this
    answerable one-handed. With two or more the CLI refuses and lists them,
    because a bare yes against two questions is a coin flip over which one
    was just allowed.
    """
    args = [verdict]
    parts = (raw_args or "").split()
    if parts:
        args.append(parts[0])
    args += ["--actor", "slack"]
    if verdict == "deny" and len(parts) > 1:
        args += ["--reason", " ".join(parts[1:])[:200]]
    _, output = _run(args)
    return output or "no response from the approval store"


def approve(raw_args: str = "") -> str:
    return _decide("approve", raw_args)


def deny(raw_args: str = "") -> str:
    return _decide("deny", raw_args)


def register(ctx) -> None:
    ctx.register_command(
        "ris-pending",
        handler=pending,
        description="List Ristretto flows waiting on an approval.",
    )
    ctx.register_command(
        "ris-approve",
        handler=approve,
        description="Allow what a waiting Ristretto flow asked to do.",
        args_hint="[request-id]",
    )
    ctx.register_command(
        "ris-deny",
        handler=deny,
        description="Refuse what a waiting Ristretto flow asked to do.",
        args_hint="[request-id] [reason]",
    )
