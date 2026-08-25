"""Read-only fleet view over the kanban board and Ristretto's event log.

Phase 2 of the control surface: it observes and nothing else. There are no
mutating routes, so the worst a compromised viewer can do is read a task list.
Controls arrive with the privilege split that should accompany them.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from .. import events
from . import data

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.filters["duration"] = data.humanise
TEMPLATES.env.filters["timestamp"] = lambda value: (
    time.strftime("%H:%M:%S", time.localtime(value)) if value else "—"
)

app = FastAPI(title="Ris", docs_url=None, redoc_url=None, openapi_url=None)


def _snapshot() -> dict[str, Any]:
    runs = data.fleet()
    live = [r for r in runs if r.status in data.LIVE_STATES]
    return {
        "runs": runs,
        "grouped": data.grouped(runs),
        "live": len(live),
        "stalled": len([r for r in runs if r.health == "stalled"]),
        "blocked": len([r for r in runs if r.health == "blocked"]),
    }


@app.get("/", response_class=HTMLResponse)
def fleet(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, "fleet.html", _snapshot())


@app.get("/task/{task_id}", response_class=HTMLResponse)
def task(request: Request, task_id: str) -> HTMLResponse:
    detail = data.task_detail(task_id)
    task_row = detail.get("task") or {}
    recorded = events.read(task_id, limit=500)
    run = data.build_run(task_row, recorded) if task_row else None
    return TEMPLATES.TemplateResponse(
        request,
        "task.html",
        {
            "run": run,
            "task_id": task_id,
            "runs": detail.get("runs") or [],
            "comments": detail.get("comments") or [],
            "timeline": list(reversed(recorded)),
        },
        status_code=200 if run else 404,
    )


@app.get("/healthz")
def healthz() -> JSONResponse:
    return JSONResponse({"ok": True})


@app.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    """Push a compact fleet summary whenever it changes.

    Only the digest is compared, so a quiet fleet costs one query every few
    seconds and sends nothing.
    """

    async def publish():
        previous = None
        while True:
            if await request.is_disconnected():
                return
            snapshot = _snapshot()
            digest = [
                (r.task_id, r.status, r.stage, r.health, r.last_signal_at)
                for r in snapshot["runs"]
            ]
            if digest != previous:
                previous = digest
                payload = {
                    "live": snapshot["live"],
                    "stalled": snapshot["stalled"],
                    "blocked": snapshot["blocked"],
                    "runs": [
                        {
                            "id": r.task_id,
                            "status": r.status,
                            "health": r.health,
                            "stage": r.stage,
                            "elapsed": data.humanise(r.elapsed),
                            "signal": data.humanise(r.age_of_signal),
                        }
                        for r in snapshot["runs"]
                    ],
                }
                yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(3)

    return StreamingResponse(
        publish(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
