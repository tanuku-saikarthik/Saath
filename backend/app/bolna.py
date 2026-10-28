"""Thin Bolna REST client (docs: https://www.bolna.ai/docs/quickstarts/api)."""
from __future__ import annotations

from typing import Any

import httpx

from .config import settings

TERMINAL = {"completed", "no-answer", "busy", "failed", "canceled", "stopped", "error", "balance-low"}


class BolnaError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    if not settings.BOLNA_API_KEY:
        raise BolnaError("BOLNA_API_KEY not set")
    return {"Authorization": f"Bearer {settings.BOLNA_API_KEY}", "Content-Type": "application/json"}


def place_call(agent_id: str, phone: str, user_data: dict[str, Any]) -> str:
    """POST /call → execution_id. user_data fills {{variables}} in the agent prompt and welcome message."""
    if not agent_id:
        raise BolnaError("Bolna agent id not set for this language (BOLNA_AGENT_ID_TE / BOLNA_AGENT_ID_HI)")
    body: dict[str, Any] = {"agent_id": agent_id, "recipient_phone_number": phone, "user_data": user_data}
    if settings.BOLNA_FROM_NUMBER:
        body["from_phone_number"] = settings.BOLNA_FROM_NUMBER
    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{settings.BOLNA_BASE_URL}/call", headers=_headers(), json=body)
    if resp.status_code >= 400:
        raise BolnaError(f"Bolna /call HTTP {resp.status_code}: {resp.text[:400]}")
    data = resp.json()
    exec_id = data.get("execution_id")
    if not exec_id:
        raise BolnaError(f"No execution_id in Bolna response: {data}")
    return exec_id


def get_execution(execution_id: str) -> dict[str, Any]:
    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{settings.BOLNA_BASE_URL}/executions/{execution_id}", headers=_headers())
    if resp.status_code >= 400:
        raise BolnaError(f"Bolna execution HTTP {resp.status_code}: {resp.text[:400]}")
    return resp.json()
