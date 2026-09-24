"""Reading a setting that has two names for one release.

Every `RISTRETTO_*` variable became `CUZAM_*` on 2026-09-24, and every
`RIS_*` became `ZAM_*`. The old names are still read here, so an environment
exported before the rename — a shell profile, a launchd plist, a cron job, a
worktree that was already running when the release landed — keeps working.

That last case is why this is code rather than a line in the upgrade guide.
An unread `RISTRETTO_STATE_HOME` does not raise. It resolves quietly to the
default, so a run would open an empty event store at `~/.cuzam` while the
real one sat beside it under the old name, and every surface would agree
that nothing had ever happened.

The deprecation is said out loud, once per variable per process: a fallback
nobody is told about is a fallback nobody removes.

Remove in 0.3.0, with the console-script aliases in pyproject.toml.
"""

from __future__ import annotations

import os
import sys
from typing import Mapping

# Explicit, and checked below. Deriving the old name by chopping at the first
# underscore would turn a typo into a silent no-fallback.
LEGACY_PREFIX = {"CUZAM_": "RISTRETTO_", "ZAM_": "RIS_"}

_announced: set[str] = set()


def legacy_name(name: str) -> str:
    """The pre-rename spelling of `name`."""
    for prefix, legacy in LEGACY_PREFIX.items():
        if name.startswith(prefix):
            return legacy + name[len(prefix) :]
    raise ValueError(
        f"{name!r} is not a renamed variable; "
        f"expected one of {sorted(LEGACY_PREFIX)} as a prefix"
    )


def get(
    name: str,
    default: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """`name` under its current spelling, falling back to the old one.

    An empty value counts as set, the same way the shell's `${X:-}` does not
    but `${X+set}` does — because exporting `CUZAM_STATE_HOME=""` to mean
    "use the default" should not then be overridden by a stale
    `RISTRETTO_STATE_HOME` left in the same environment.
    """
    env = os.environ if environ is None else environ
    if name in env:
        return env[name]

    old = legacy_name(name)
    if old in env:
        if old not in _announced:
            _announced.add(old)
            print(
                f"{old} is deprecated and will stop being read in 0.3.0; "
                f"rename it to {name}",
                file=sys.stderr,
            )
        return env[old]
    return default
