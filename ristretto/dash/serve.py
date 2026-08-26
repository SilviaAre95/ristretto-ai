"""Bind the fleet view to the private network and nothing wider.

The dashboard exists to be reached from a phone, which is exactly what makes
a careless bind dangerous. It listens on the tailnet address when there is
one and on loopback otherwise; 0.0.0.0 is refused rather than defaulted to,
because the difference between "reachable from my iPad" and "reachable from
the coffee shop wifi" is one absent-minded flag.
"""

from __future__ import annotations

import shutil
import subprocess


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


def resolve_host(requested: str | None = None) -> tuple[str, str]:
    """Return (host, why). Refuses any address that is not private."""
    if requested:
        if requested in {"0.0.0.0", "::", "*"}:
            raise BindRefused(
                f"refusing to listen on {requested}: the dashboard can read your task "
                "board and must stay on the tailnet or loopback"
            )
        return requested, "requested"
    address = tailnet_address()
    if address:
        return address, "tailnet"
    return "127.0.0.1", "loopback (Tailscale unavailable)"


def run(host: str | None = None, port: int = 8787, reload: bool = False) -> int:
    import uvicorn

    bind, why = resolve_host(host)
    print(f"ris-dash: http://{bind}:{port}  ({why})")
    uvicorn.run(
        "ristretto.dash.app:app",
        host=bind,
        port=port,
        reload=reload,
        log_level="warning",
        access_log=False,
    )
    return 0
