"""Mid-call tools Bolna's agent can call (custom functions, see prompts/bolna_tools.md).

`alert_family_urgent`: the parent mentioned a fall, chest pain, breathlessness and so on. Saath
raises the urgent alert right away instead of after hang-up, and the reply tells the agent what to
say next (and whether to transfer her to the child).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlmodel import select

from .config import settings
from .db import session_scope
from .models import Call, Family, Parent
from .mood import urgent_alert_now
from .notify import notify_alert

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks/bolna/tools")


def _digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())[-10:]


def _check_token(request: Request) -> None:
    if not settings.TOOL_TOKEN:
        return
    sent = request.headers.get("authorization", "") or request.query_params.get("token", "")
    if sent.removeprefix("Bearer ").strip() != settings.TOOL_TOKEN:
        raise HTTPException(401, "Bad tool token")


async def _params(request: Request) -> dict[str, Any]:
    """Bolna's docs don't say whether a tool sends a query string or a JSON body, so accept both."""
    params: dict[str, Any] = dict(request.query_params)
    if request.method != "GET":
        try:
            body = await request.json()
            if isinstance(body, dict):
                params.update(body)
        except Exception:
            form = await request.form()
            params.update({k: str(v) for k, v in form.items()})
    return params


@router.get("/urgent", operation_id="urgent_tool_get")
@router.post("/urgent", operation_id="urgent_tool_post")
async def urgent(request: Request) -> dict[str, Any]:
    _check_token(request)
    p = await _params(request)
    reason = str(p.get("reason") or "").strip()
    exec_id = str(p.get("execution_id") or "").strip()
    number = _digits(str(p.get("to_number") or p.get("parent_phone") or ""))

    with session_scope() as session:
        call = session.exec(select(Call).where(Call.bolna_execution_id == exec_id)).first() if exec_id else None
        parent = session.get(Parent, call.parent_id) if call else None
        if parent is None and number:
            parent = next((x for x in session.exec(select(Parent)).all() if _digits(x.phone) == number), None)
            if parent is not None:
                call = session.exec(
                    select(Call).where(Call.parent_id == parent.id, Call.status.in_(["queued", "in_progress"])).order_by(Call.scheduled_at.desc())
                ).first()
        if parent is None:
            log.warning("Urgent tool call for an unknown call: %s", p)
            return {"status": "unknown_call", "message": "Tell her to call a neighbour or 108 right now if she needs help."}
        family = session.get(Family, parent.family_id)
        child = family.child_name if family else "her family"
        alert = urgent_alert_now(session, parent, call, reason)
        session.commit()
        alert_id = alert.id if alert else None

    if alert_id:
        notify_alert(alert_id, mid_call=True)
    if settings.TRANSFER_ON_EMERGENCY:
        say = f"{child} has been alerted. Tell her calmly that you are connecting her to {child} right now, then transfer the call."
    else:
        say = f"{child} has been alerted right away. Tell her calmly that {child} knows, and that if she needs help now she should call a neighbour or 108."
    return {"status": "alerted", "message": say}
