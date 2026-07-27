"""CLI glue for the ops daemon: a dry `--check` and the live runner."""
from __future__ import annotations

from collections.abc import Mapping

from .config import load_ops_config
from .identity import allowed_user_ids


def ops_daemon_check(environ: Mapping[str, str], repos: Mapping[str, str]) -> tuple[int, str]:
    if not environ.get("TELEGRAM_BOT_TOKEN"):
        return 1, "missing TELEGRAM_BOT_TOKEN in environment (~/.hermes/.env)"
    if not allowed_user_ids(environ):
        return 1, "missing TELEGRAM_ALLOWED_USERS in environment (~/.hermes/.env)"
    if not repos:
        return 1, "no repositories configured; run `ristretto configure --repository ...`"
    return 0, f"ops-daemon ready: {len(repos)} repo(s), identity lock armed"


def run_ops_daemon(environ: Mapping[str, str], repos: Mapping[str, str]) -> int:  # pragma: no cover
    from .daemon import OpsDaemon
    from .telegram_api import TelegramClient

    code, msg = ops_daemon_check(environ, repos)
    print(msg)
    if code != 0:
        return code
    cfg = load_ops_config(environ)
    client = TelegramClient(environ["TELEGRAM_BOT_TOKEN"])
    daemon = OpsDaemon(client, repos, cfg, allowed_user_ids(environ))
    daemon.run()
    return 0
