"""Talk to Zam from Slack.

The loop reads the fleet and the vault, but until now only on the dashboard.
The vision is talking to Zam on the go, so this reaches the same loop from
the one surface you have on a phone — and keeps the thread: a Slack channel is
one continuous conversation, because the CLI is told the channel is the
conversation key.

Unlike the deterministic commands (approve, launch), this DOES route to a
model — it is a conversation. But it is Zam's own read-only loop: it can look
at the fleet and the vault and answer, and it has no tool that changes
anything. Acting still goes through the gate, separately.
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
        description="Talk to Zam: !zam <question> — reads the fleet and your vault.",
        args_hint="<question>",
    )
