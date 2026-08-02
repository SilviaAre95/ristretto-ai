"""CLI glue for the ops daemon: a dry `--check` and the live runner."""
from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from .config import load_ops_config
from .identity import allowed_user_ids

KEYCHAIN_SERVICE = "ristretto-ops-telegram"
OPS_ENV_PATH = Path("~/.config/ristretto/ops.env").expanduser()


def _keychain_token() -> str | None:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def resolve_bot_token(
    environ: Mapping[str, str], *, keychain=_keychain_token
) -> str | None:
    """Resolve the bot token: env override first, else the macOS Keychain.

    Keeping the token in Keychain means it never lives in a plaintext file, so
    it can't leak via a file diff and is encrypted at rest."""
    tok = environ.get("TELEGRAM_BOT_TOKEN", "")
    if tok and not tok.startswith("REPLACE_ME"):
        return tok
    return keychain()


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


def ops_daemon_check(
    environ: Mapping[str, str], *, keychain=_keychain_token
) -> tuple[int, str]:
    if not resolve_bot_token(environ, keychain=keychain):
        return 1, (
            "missing bot token — store it in Keychain:\n  security "
            f"add-generic-password -a \"$USER\" -s {KEYCHAIN_SERVICE} -w"
        )
    if not allowed_user_ids(environ):
        return 1, "missing/invalid TELEGRAM_ALLOWED_USERS (set your numeric id in ~/.config/ristretto/ops.env)"
    cfg = load_ops_config(environ)
    if not cfg.root_dir.exists():
        return 1, f"root dir does not exist: {cfg.root_dir} (set RISTRETTO_OPS_ROOT)"
    return 0, f"ops-daemon ready: rooted at {cfg.root_dir}, identity lock armed"


OPS_ENV_TEMPLATE = """\
# Ristretto ops lane — private config for the Telegram phone lane.
# The bot TOKEN is NOT here — it lives in your macOS Keychain (see ops-init
# output). This file holds only non-secret settings.

# Your numeric Telegram user ID (from @userinfobot):
TELEGRAM_ALLOWED_USERS=REPLACE_ME_WITH_YOUR_NUMERIC_ID

# Working root that phone sessions open in (roam / create repos under here):
RISTRETTO_OPS_ROOT={root}
"""


def ops_init(environ: Mapping[str, str]) -> int:  # pragma: no cover
    """Scaffold the ops-lane config and print the one Keychain command to run."""
    OPS_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if OPS_ENV_PATH.exists():
        print(f"config already exists: {OPS_ENV_PATH} (left as-is)")
    else:
        default_root = str(Path("~/code").expanduser())
        OPS_ENV_PATH.write_text(OPS_ENV_TEMPLATE.format(root=default_root))
        OPS_ENV_PATH.chmod(0o600)
        print(f"created {OPS_ENV_PATH} (chmod 600)")
    print(
        "\nNext:\n"
        f"  1. Store your bot token in Keychain (run this yourself — the value\n"
        f"     is not echoed and never touches a file):\n"
        f"       security add-generic-password -a \"$USER\" -s {KEYCHAIN_SERVICE} -w\n"
        f"  2. Put your numeric Telegram id + working root in {OPS_ENV_PATH}\n"
        f"  3. Verify:  ristretto ops-daemon --check\n"
    )
    load_ops_env()
    code, msg = ops_daemon_check(os.environ)
    print(msg)
    return 0


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
    client = TelegramClient(resolve_bot_token(environ))
    daemon = OpsDaemon(client, cfg, allowed_user_ids(environ))
    daemon.run()
    return 0
