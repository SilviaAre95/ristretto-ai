"""CLI glue for the ops daemon: a dry `--check` and the live runner."""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from .config import load_ops_config
from .identity import allowed_user_ids


def _parse_env_file(env_path: Path) -> None:
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if val[:1] in ("'", '"'):
            # Quoted value: take the content between the quotes (keeps any #).
            quote = val[0]
            val = val[1:].split(quote, 1)[0]
        else:
            # Unquoted: strip a trailing inline comment ( #… or \t#…).
            for sep in (" #", "\t#"):
                if sep in val:
                    val = val.split(sep, 1)[0]
            val = val.strip()
        if key and key not in os.environ:
            os.environ[key] = val


def load_ops_env() -> None:
    """Load the ops-lane's OWN env file, isolated from Hermes's ~/.hermes/.env.

    Order: $RISTRETTO_OPS_ENV, then ~/.config/ristretto/ops.env. Falls back to
    the shared ~/.hermes/.env only if no dedicated file exists (with a nudge to
    isolate), so the bot token can live entirely outside Hermes's config and can
    never be picked up by the gateway's Telegram platform."""
    override = os.environ.get("RISTRETTO_OPS_ENV")
    dedicated = [Path(override).expanduser()] if override else []
    dedicated.append(Path("~/.config/ristretto/ops.env").expanduser())
    for path in dedicated:
        if path.exists():
            _parse_env_file(path)
            return
    shared = Path("~/.hermes/.env").expanduser()
    if shared.exists():
        _parse_env_file(shared)
        print(
            "note: ops-lane read ~/.hermes/.env (shared with Hermes). For clean "
            "isolation, move TELEGRAM_* + RISTRETTO_OPS_* to "
            "~/.config/ristretto/ops.env."
        )


def ops_daemon_check(environ: Mapping[str, str]) -> tuple[int, str]:
    if not environ.get("TELEGRAM_BOT_TOKEN"):
        return 1, "missing TELEGRAM_BOT_TOKEN in environment (~/.hermes/.env)"
    if not allowed_user_ids(environ):
        return 1, "missing TELEGRAM_ALLOWED_USERS in environment (~/.hermes/.env)"
    cfg = load_ops_config(environ)
    if not cfg.root_dir.exists():
        return 1, f"root dir does not exist: {cfg.root_dir} (set RISTRETTO_OPS_ROOT)"
    return 0, f"ops-daemon ready: rooted at {cfg.root_dir}, identity lock armed"


def run_ops_daemon(environ: Mapping[str, str]) -> int:  # pragma: no cover
    from .daemon import OpsDaemon
    from .telegram_api import TelegramClient

    load_ops_env()
    environ = os.environ
    code, msg = ops_daemon_check(environ)
    print(msg)
    if code != 0:
        return code
    cfg = load_ops_config(environ)
    client = TelegramClient(environ["TELEGRAM_BOT_TOKEN"])
    daemon = OpsDaemon(client, cfg, allowed_user_ids(environ))
    daemon.run()
    return 0
