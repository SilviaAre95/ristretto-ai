"""Talk to Zam from Slack.

The loop was reachable only from the dashboard and the CLI until now.
The vision is talking to Zam on the go, so this reaches the same loop from
the one surface you have on a phone — and keeps the thread: a Slack channel is
one continuous conversation, because the CLI is told the channel is the
conversation key.

Unlike the deterministic commands (approve, launch), this DOES route to a
model — it is a conversation.

It reaches Zam's whole loop, not a read-only slice of it. That is worth
saying plainly, because this docstring used to claim the opposite: the loop
allowlists every tool it has for every surface, so from Slack the model can
also propose a merge (gated — it records an approval and cannot merge) and
start a coding run (not gated — it executes, ending at a pull request).
`slack-gateway` bounds who can reach this to one allowlisted user, which is
what makes it acceptable; it is not made acceptable by the tools being
harmless, because two of them are not.
"""

from __future__ import annotations

import shutil
import subprocess

# A conversation turn is a model call with tool use; give it room without
# hanging the chat forever.
TIMEOUT_SECONDS = 200


def _cuzam() -> str | None:
    return shutil.which("cuzam")


def ask(raw_args: str = "", _channel: str = "") -> str:
    """One turn with Zam. The channel scopes the conversation's memory."""
    binary = _cuzam()
    if not binary:
        return "Zam is not on PATH for the gateway process."
    message = (raw_args or "").strip()
    if not message:
        return "Ask me something — e.g. !zam what's on the fleet right now?"

    # A per-channel conversation key so the thread continues. The channel id is
    # not always handed to a plugin command handler, so fall back to a shared
    # key; a shared thread is better than none, and the dashboard has its own.
    conversation = f"slack:{_channel}" if _channel else "slack:default"
    try:
        result = subprocess.run(
            [binary, "chat", message, "--conversation", conversation],
            capture_output=True, text=True, check=False, timeout=TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"I couldn't reach my own loop: {exc}"
    return (result.stdout or result.stderr or "no answer").strip()


def register(ctx) -> None:
    ctx.register_command(
        "zam",
        handler=ask,
        description=(
            "Talk to Zam: !zam <question> — reads the fleet and your vault, "
            "and can start a run or queue a PR for your approval."
        ),
        args_hint="<question>",
    )
