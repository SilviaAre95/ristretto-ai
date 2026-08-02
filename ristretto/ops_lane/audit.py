"""Append-only JSONL audit log for ops-lane approval activity."""
from __future__ import annotations

import json
import time
from pathlib import Path


def audit(path: Path, event: dict, now=time.time) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": now(), **event}
    with path.open("a") as handle:
        handle.write(json.dumps(record) + "\n")
