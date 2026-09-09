"""Bind the fleet view to the private network and nothing wider.

The dashboard exists to be reached from a phone, which is exactly what makes
a careless bind dangerous. It listens on the tailnet address when there is
one and on loopback otherwise; 0.0.0.0 is refused rather than defaulted to,
because the difference between "reachable from my iPad" and "reachable from
the coffee shop wifi" is one absent-minded flag.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
import subprocess
import sys


class BindRefused(RuntimeError):
    """Raised when asked to listen somewhere that is not private."""


def tailnet_address(timeout: int = 5) -> str | None:
    """This machine's Tailscale IPv4 address, if Tailscale is up."""
    if shutil.which("tailscale") is None:
        return None
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    first = result.stdout.strip().splitlines()
    return first[0].strip() if first else None


def tailnet_name(timeout: int = 5) -> str | None:
    """This machine's MagicDNS name, if Tailscale is up and has assigned one.

    Links are read on a phone, where a bare 100.x address is both opaque and
    brittle — it changes if the machine is re-added to the tailnet, and every
    link already sent then points nowhere. The MagicDNS name survives that.
    """
    if shutil.which("tailscale") is None:
        return None
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        name = json.loads(result.stdout).get("Self", {}).get("DNSName") or ""
    except (ValueError, AttributeError):
        return None
    name = name.strip().rstrip(".")
    # A hostname with no domain is not resolvable off this machine, so it is
    # no better than the address it would replace.
    return name if name and "." in name else None


# The address that means "this machine, to itself". Useless in a link that
# someone else opens, so callers that build links check for it.
LOOPBACK = "127.0.0.1"

# How hard to try for the tailnet before settling for an address nobody else
# can reach. Short enough not to delay a genuine offline start by much, long
# enough to ride out Tailscale still coming up at login or flapping during a
# reload.
BIND_RESOLVE_ATTEMPTS = 5
BIND_RESOLVE_BACKOFF = 2.0


def link_host() -> str:
    """The host to put in a link someone will open on another device.

    Deliberately separate from the bind address: what this process listens on
    and what a phone can resolve are different questions, and conflating them
    is how a link ends up pointing at 127.0.0.1.
    """
    return tailnet_name() or tailnet_address() or LOOPBACK


def resolve_host(requested: str | None = None) -> tuple[str, str]:
    """Return (host, why). Refuses any address that is not private."""
    if requested:
        if requested in {"0.0.0.0", "::", "*"}:
            raise BindRefused(
                f"refusing to listen on {requested}: the dashboard can read your task "
                "board and must stay on the tailnet or loopback"
            )
        return requested, "requested"
    # Retried, because a single failed lookup is usually a blip rather than an
    # answer. The service restarts on every source edit (--reload is the
    # deployment mechanism, deliberately), and one restart that happened to
    # catch Tailscale mid-flap silently pinned the dashboard to loopback for
    # hours: healthz answered on localhost, every doorbell link pointed at the
    # tailnet name, and nothing anywhere said the two disagreed.
    #
    # Loopback is not a degraded binding here, it is an unreachable one, so it
    # is worth waiting a few seconds before accepting it.
    for attempt in range(BIND_RESOLVE_ATTEMPTS):
        address = tailnet_address()
        if address:
            return address, "tailnet"
        if attempt + 1 < BIND_RESOLVE_ATTEMPTS:
            time.sleep(BIND_RESOLVE_BACKOFF)
    return LOOPBACK, "loopback (Tailscale unavailable)"


def run(host: str | None = None, port: int = 8787, reload: bool = False) -> int:
    """Serve the fleet view.

    `reload` is how this deploys. Four times in one day the dashboard served
    code hours older than the checkout — a run reported stalled because the
    process predated the fix, the approval banner missing for the same reason,
    a question mis-transcribed after the transcription had been fixed. Every
    time the remedy was "restart it by hand", which is not a remedy, it is a
    thing to forget.

    Watching only the package: editing docs or tests should not bounce a
    server someone is looking at.
    """
    import uvicorn

    bind, why = resolve_host(host)
    print(f"ris-dash: http://{bind}:{port}  ({why}){'  [reloading]' if reload else ''}")
    if bind == LOOPBACK and not host:
        # Every doorbell notification links to the tailnet name, so this
        # is not a dashboard that works locally — it is one that answers
        # nobody. Say so where an operator will actually see it.
        print(
            "ris-dash: WARNING bound to loopback — every link in every "
            "notification points at the tailnet address and will not "
            "resolve. Restart once Tailscale is up: "
            "launchctl kickstart -k gui/$(id -u)/com.ristretto.dash",
            file=sys.stderr,
        )
    uvicorn.run(
        "ristretto.dash.app:app",
        host=bind,
        port=port,
        reload=reload,
        reload_dirs=[str(Path(__file__).resolve().parents[1])] if reload else None,
        log_level="warning",
        access_log=False,
    )
    return 0
