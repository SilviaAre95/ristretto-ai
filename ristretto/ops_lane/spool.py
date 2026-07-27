"""File-spool IPC between the ops daemon and the approval broker.

Atomic writes via a temp file + os.replace so a reader never sees a partial
JSON document. One request file and one decision file per request id."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path


def _validate_request_id(request_id: str) -> None:
    """Validate request_id to prevent path traversal attacks.

    Raises ValueError if the request_id contains path separators, relative
    references, null bytes, or is empty/dot.
    """
    if (
        not request_id
        or request_id in (".", "..")
        or "/" in request_id
        or "\\" in request_id
        or "\x00" in request_id
        or os.path.basename(request_id) != request_id
    ):
        raise ValueError(f"unsafe request id: {request_id!r}")


class Spool:
    def __init__(self, directory: Path) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _write_atomic(self, path: Path, payload: dict) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(payload, handle)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def _request_path(self, request_id: str) -> Path:
        _validate_request_id(request_id)
        return self.dir / f"{request_id}.request.json"

    def _decision_path(self, request_id: str) -> Path:
        _validate_request_id(request_id)
        return self.dir / f"{request_id}.decision.json"

    def write_request(self, request_id: str, payload: dict) -> Path:
        path = self._request_path(request_id)
        self._write_atomic(path, payload)
        return path

    def read_new_requests(self) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        for path in sorted(self.dir.glob("*.request.json")):
            request_id = path.name[: -len(".request.json")]
            if self._decision_path(request_id).exists():
                continue
            try:
                out.append((request_id, json.loads(path.read_text())))
            except (json.JSONDecodeError, OSError):
                continue
        return out

    def write_decision(self, request_id: str, decision: dict) -> None:
        self._write_atomic(self._decision_path(request_id), decision)

    def await_decision(
        self,
        request_id: str,
        timeout_s: float,
        poll_s: float = 0.25,
        sleep=time.sleep,
        now=time.monotonic,
    ) -> dict | None:
        deadline = now() + timeout_s
        path = self._decision_path(request_id)
        while now() < deadline:
            if path.exists():
                try:
                    return json.loads(path.read_text())
                except (json.JSONDecodeError, OSError):
                    return None
            sleep(poll_s)
        return None
