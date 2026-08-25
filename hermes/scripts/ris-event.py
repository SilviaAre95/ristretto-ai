#!/usr/bin/env python3
"""Emit one Ristretto pipeline event from a shell call site.

Used by run-loop.sh, whose classic path is a shell script rather than the
multi-stage Python runner. Always exits 0: a call site that could fail the
build it is only describing would be worse than no telemetry at all. Callers
should still append `|| true` so a missing interpreter cannot break the loop
either.

    ris-event.py <task_id> <kind> [--issue KEY] [--project NAME]
                 [--stage NAME] [--payload JSON]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from ristretto import events
except Exception as exc:  # noqa: BLE001 - telemetry must never break a loop
    print(f"ris-event: unavailable: {exc}", file=sys.stderr)
    raise SystemExit(0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ris-event")
    parser.add_argument("task_id")
    parser.add_argument("kind")
    parser.add_argument("--issue")
    parser.add_argument("--project")
    parser.add_argument("--stage")
    parser.add_argument("--payload", help="JSON object")
    args = parser.parse_args(argv)

    payload = None
    if args.payload:
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError as exc:
            print(f"ris-event: ignoring unparsable payload: {exc}", file=sys.stderr)
    if not isinstance(payload, dict):
        payload = None if payload is None else {"value": payload}

    try:
        events.emit(
            args.task_id,
            args.kind,
            issue_key=args.issue,
            project=args.project,
            stage=args.stage,
            payload=payload,
        )
    except events.UnknownEventKind as exc:
        # A typo in a call site should be visible without stopping the run.
        print(f"ris-event: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
