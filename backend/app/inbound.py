"""The SOS line: she can call Saath any time.

Link a Bolna phone number to her language's agent for inbound calls, and set the agent's caller
identification URL to `{PUBLIC_BASE_URL}/webhooks/bolna/caller` (Bearer TOOL_TOKEN). When she calls,
Bolna asks this endpoint who is calling (it must answer within 3 seconds) and merges the reply into
the prompt variables, so Saath greets her by name, knows her medicines and recent calls, and carries
any message from her child.

After the call, the execution webhook handles it like any other call (kind "inbound"): it is scored,
and the family gets an "Amma called Saath" alert, or an urgent one if she mentioned an emergency. If
the line dropped before she spoke, Saath rings her straight back.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from sqlmodel import select

from .context import pending_notes, prepare_call, user_data_for_call
from .db import session_scope
from .models import Call, Parent
from .tools import _check_token, _digits, _params

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks/bolna")

UNKNOWN_CALLER = {
    "call_kind": "inbound", "parent_name": "the caller", "address_term": "", "child_name": "their family",
    "opening": "నమస్తే, నేను సాథ్ ని. చెప్పండి, ఏమైనా సహాయం కావాలా?", "child_message": "none", "medicines": "none", "meds_to_check": "none", "topics": "their day",
    "open_threads": "nothing specific", "avoid_topics": "none", "last_call_note": "Saath doesn't know this caller.",
    "tone_instruction": "Be calm and kind. You don't know this caller: ask how you can help, and if they need help urgently, tell them to call 108.",
    "reminder_medicine": "none", "reminder_timing": "none",
}


@router.get("/caller", operation_id="caller_lookup_get")
@router.post("/caller", operation_id="caller_lookup_post")
async def caller(request: Request) -> dict[str, Any]:
    _check_token(request)
    p = await _params(request)
    number = _digits(str(p.get("contact_number") or p.get("from_number") or ""))
    exec_id = str(p.get("execution_id") or "").strip() or None
    with session_scope() as session:
        parent = next((x for x in session.exec(select(Parent)).all() if number and _digits(x.phone) == number), None)
        if parent is None:
            log.info("Inbound call from an unknown number ending %s", number[-4:] if number else "?")
            return UNKNOWN_CALLER
        if not exec_id:  # without an execution id the row would never be matched; the webhook will create it
            return user_data_for_call(session, parent, "inbound", pending_notes(session, parent.id))
        call = session.exec(select(Call).where(Call.bolna_execution_id == exec_id)).first()
        if call is None:
            call = Call(parent_id=parent.id, kind="inbound", status="in_progress", bolna_execution_id=exec_id)
            session.add(call)
            session.flush()
        data = prepare_call(session, parent, call)  # records which of the child's messages this call carries
        session.commit()
        return data
