"""Thin Bolna REST client (docs: https://www.bolna.ai/docs/quickstarts/api)."""
from __future__ import annotations

import json
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


# ---------- keeping the transfer-call number in step with the app ----------
# Calls to her and to the family take their numbers from the database on every call, so a changed number
# just works. The one number Bolna stores itself is the Transfer Call destination on each agent, so when the
# family's number changes in the app it is updated there too.

def _digits(x: str) -> str:
    return "".join(ch for ch in str(x) if ch.isdigit())[-10:]


def _e164(x: str) -> str:
    d = "".join(ch for ch in str(x) if ch.isdigit())
    return "+91" + d if len(d) == 10 else "+" + d


def _api(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    with httpx.Client(timeout=20) as client:
        resp = client.request(method, f"{settings.BOLNA_BASE_URL}{path}", headers=_headers(), json=body)
    if resp.status_code >= 400:
        raise BolnaError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json() if resp.content else {}


def _swap_transfer(agent: dict[str, Any], old: str, new: str) -> tuple[int, str]:
    """Replace the transfer destination inside the agent's tool params. Returns (changes, current number found)."""
    changed, found = 0, ""
    for task in agent.get("tasks") or []:
        params = ((task.get("tools_config") or {}).get("api_tools") or {}).get("tools_params") or {}
        for name, conf in params.items():
            raw = conf.get("param")
            as_text = isinstance(raw, str)
            try:
                obj = json.loads(raw) if as_text else raw  # Bolna returns this as an object (the docs show a string)
            except ValueError:
                continue
            if not isinstance(obj, dict) or "call_transfer_number" not in obj:
                continue
            cur = str(obj.get("call_transfer_number", ""))
            found = cur
            if _digits(cur) == _digits(new):
                continue
            if old and _digits(cur) != _digits(old):
                continue  # a different number someone set on purpose: leave it
            obj["call_transfer_number"] = _e164(new)
            conf["param"] = json.dumps(obj) if as_text else obj
            changed += 1
    return changed, found


def sync_transfer_number(agent_id: str, old: str, new: str, dry_run: bool = False) -> str:
    """Point the agent's Transfer Call at `new`. Never raises; returns a one-line result for the app.
    dry_run reads the agent and says what it would do, without changing anything."""
    if not agent_id or not new:
        return "skipped"
    try:
        agent = _api("GET", f"/v2/agent/{agent_id}")
        changed, found = _swap_transfer(agent, old, new)
        if not found:
            return "has no Transfer Call yet. In Bolna: Tools, add Transfer Call, set " + _e164(new)
        if not changed:
            return "already set" if _digits(found) == _digits(new) else f"left alone (it is set to {found}, not your old number)"
        cfg = {k: agent[k] for k in ("agent_name", "agent_type", "tasks", "ingest_source_config", "call_summary_enabled",
                                     "agent_welcome_message", "webhook_url", "calling_guardrails") if k in agent}
        # A full update replaces the agent, so only go ahead when everything it must keep came back:
        # the welcome message, the prompts and the webhook that sends finished calls back to Saath.
        # Bolna returns more settings than the update call is documented to take (memory, dispositions, webhook
        # config, ...). Sending a partial copy back could wipe them, so refuse when any are present.
        known = set(cfg) | {"agent_prompts", "id", "created_at", "updated_at", "created_by", "agent_status", "creation_source"}
        extras = sorted(k for k, v in agent.items() if k not in known and v not in (None, "", [], {}, False))
        if extras:
            # Not safe to rewrite from here. Tell the family exactly what to change by hand.
            return f"change it in Bolna: Tools, Transfer call, set {_e164(new)} (now {found})"
        missing = [k for k in ("agent_welcome_message", "webhook_url") if not cfg.get(k)] + ([] if agent.get("agent_prompts") else ["agent_prompts"])
        if missing:
            return f"couldn't be updated safely from here (Bolna didn't return: {', '.join(missing)})"
        if dry_run:
            return f"would update {changed} transfer setting(s) from {found} to {_e164(new)}; all required fields present"
        _api("PUT", f"/v2/agent/{agent_id}", {"agent_config": cfg, "agent_prompts": agent["agent_prompts"]})
        after = _api("GET", f"/v2/agent/{agent_id}")
        _, now = _swap_transfer(after, _e164(new), _e164(new))
        return "updated" if _digits(now) == _digits(new) else "sent, but Bolna still shows the old number"
    except (BolnaError, httpx.HTTPError, ValueError) as exc:
        return f"couldn't be updated ({exc})"
