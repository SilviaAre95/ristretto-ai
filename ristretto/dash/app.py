"""Fleet view over the kanban board and Ristretto's event log.

Reading is open to anyone who can reach the tailnet address. The mutating
routes are not: there is no login here, so they are same-origin only and
every action they take is recorded in the event log. Approving a tool call a
flow is blocked on is the most consequential of them, and answers race
against Slack, so the store decides the winner rather than this layer.

Starting work is deliberately absent. Stopping a run costs a restart;
launching one spends tokens and writes code, and that deserves its own
design rather than a third button added by analogy.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates

from .. import approvals, events
from . import chat, control, data, launch as launcher

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.filters["duration"] = data.humanise
TEMPLATES.env.filters["ago"] = data.ago
TEMPLATES.env.filters["timestamp"] = lambda value: (
    time.strftime("%H:%M:%S", time.localtime(value)) if value else "—"
)

app = FastAPI(title="Ris", docs_url=None, redoc_url=None, openapi_url=None)


def _snapshot(show_all: bool = False) -> dict[str, Any]:
    everything = data.fleet()
    shown, hidden = (everything, 0) if show_all else data.recent(everything)
    return {
        "runs": shown,
        "grouped": data.grouped(shown),
        "hidden": hidden,
        "show_all": show_all,
        "total": len(everything),
        "live": len([r for r in everything if r.status in data.LIVE_STATES]),
        "stalled": len([r for r in everything if r.health == "stalled"]),
        "blocked": len([r for r in everything if r.health == "blocked"]),
        # A flow stopped waiting on a person is the one thing that must not
        # need drilling into a task page to notice.
        "waiting": approvals.pending(),
        "build": data.build_stamp(),
    }


@app.get("/", response_class=HTMLResponse)
def fleet(request: Request, all: bool = False) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, "fleet.html", _snapshot(all))


@app.get("/task/{task_id}", response_class=HTMLResponse)
def task(request: Request, task_id: str, ok: str | None = None, failed: str | None = None) -> HTMLResponse:
    detail = data.task_detail(task_id)
    task_row = detail.get("task") or {}
    recorded = events.read(task_id, limit=500)
    run = data.build_run(task_row, recorded) if task_row else None
    now = int(time.time())
    waiting = [
        {**item, "minutes_left": max(0, item["expires_at"] - now) // 60}
        for item in approvals.pending(task_id=task_id)
    ]
    return TEMPLATES.TemplateResponse(
        request,
        "task.html",
        {
            "run": run,
            "task_id": task_id,
            "runs": detail.get("runs") or [],
            "comments": detail.get("comments") or [],
            "timeline": list(reversed(recorded)),
            "waiting": waiting,
            "build": data.build_stamp(),
            "ok": ok,
            "failed": failed,
        },
        status_code=200 if run else 404,
    )


def require_same_origin(request: Request) -> None:
    """Reject a mutating request that did not come from this page.

    There is no login here, so without this check any site you happened to
    visit while on the tailnet could post to the dashboard from your browser
    and stop your agents. Browsers send Sec-Fetch-Site on every request and
    cannot be talked out of it from script, so its absence is treated as
    suspicious rather than waved through.
    """
    site = request.headers.get("sec-fetch-site")
    # Only same-origin. "none" means the request was not triggered by a page
    # at all, which a form post cannot be, so it is not an exemption here.
    if site == "same-origin":
        return
    if site is None:
        origin = request.headers.get("origin")
        host = request.headers.get("host")
        if origin and host and origin.split("://")[-1] == host:
            return
    raise HTTPException(status_code=403, detail="cross-site requests are refused")


@app.get("/launch", response_class=HTMLResponse)
def launch_form(request: Request, ok: str | None = None, failed: str | None = None) -> HTMLResponse:
    context = launcher.options()
    context.update(
        {"active": launcher.active_runs(), "ok": ok, "failed": failed, "build": data.build_stamp()}
    )
    return TEMPLATES.TemplateResponse(request, "launch.html", context)


@app.post("/launch")
async def start_run(request: Request) -> RedirectResponse:
    """Start a supervised run.

    The only route here that spends money and writes to a branch, so it is a
    deliberate page rather than a control added to the fleet view by analogy
    with stop. Every guard lives in launch.launch(), which the CLI calls too,
    so the surface that is tested is the surface that is used.
    """
    require_same_origin(request)
    form = await request.form()
    outcome = launcher.launch(
        str(form.get("project", "")),
        str(form.get("issue", "")).strip().upper(),
        str(form.get("flow", "")),
        actor="dashboard",
        allow_busy=bool(form.get("allow_busy")),
        unattended=bool(form.get("unattended")),
    )
    if outcome.ok and outcome.task_id:
        return RedirectResponse(
            f"/task/{quote(outcome.task_id)}?ok={quote(outcome.message[:300])}", status_code=303
        )
    field = "ok" if outcome.ok else "failed"
    return RedirectResponse(
        f"/launch?{field}={quote(outcome.message[:300])}", status_code=303
    )


@app.post("/approval/{request_id}/approve")
def approve(request: Request, request_id: str) -> RedirectResponse:
    return _answer(request, request_id, approvals.ALLOW)


@app.post("/approval/{request_id}/deny")
async def deny(request: Request, request_id: str) -> RedirectResponse:
    """Refuse, optionally saying why.

    The reason is not decoration: the broker relays it as the deny message,
    which is the one channel that reaches the model. For a stage asking a
    question rather than asking permission, that text is the answer.
    """
    form = await request.form()
    return _answer(request, request_id, approvals.DENY, reason=str(form.get("reason", "")).strip())


def _answer(
    request: Request, request_id: str, verdict: str, reason: str = ""
) -> RedirectResponse:
    """Answer a pending approval, then go back to the task that asked.

    Same-origin like every other mutating route. Losing the race to Slack is
    reported plainly rather than as a failure: the question was answered,
    just not here.
    """
    require_same_origin(request)
    item = approvals.get(request_id)
    won, message = approvals.decide(request_id, verdict, actor="dashboard", reason=reason)
    task_id = (item or {}).get("task_id", "")
    status = "ok" if won else "failed"
    detail = quote((("allowed" if verdict == approvals.ALLOW else "denied") if won else message)[:300])
    if not task_id:
        return RedirectResponse(f"/?{status}={detail}", status_code=303)
    return RedirectResponse(f"/task/{quote(task_id)}?{status}={detail}", status_code=303)


@app.post("/task/{task_id}/stop")
def stop_task(request: Request, task_id: str) -> RedirectResponse:
    require_same_origin(request)
    outcome = control.stop(task_id)
    return _back_to_task(task_id, outcome)


@app.post("/task/{task_id}/unblock")
def unblock_task(request: Request, task_id: str) -> RedirectResponse:
    require_same_origin(request)
    outcome = control.unblock(task_id)
    return _back_to_task(task_id, outcome)


def _back_to_task(task_id: str, outcome: control.Outcome) -> RedirectResponse:
    status = "ok" if outcome.ok else "failed"
    detail = quote(outcome.message[:300])
    return RedirectResponse(
        f"/task/{quote(task_id)}?{status}={detail}", status_code=303
    )


@app.post("/chat")
async def ask_ris(request: Request) -> JSONResponse:
    """Put a question to Ris with the fleet as context.

    Same-origin like the other mutating routes. It does not change anything,
    but it does spend a model turn, and an endpoint anyone can drive is one
    anyone can drain.
    """
    require_same_origin(request)
    body = await request.json()
    reply = chat.ask(str(body.get("message", "")))
    return JSONResponse({"ok": reply.ok, "text": reply.text}, status_code=200 if reply.ok else 400)


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
