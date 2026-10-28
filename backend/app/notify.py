"""Getting alerts and summaries to the child outside the app.

Two channels, both optional and independent:
- **Saath calls the child** through a second Bolna agent (prompts/agent_alert_en.md) that reads out
  the alert in English. Needs BOLNA_AGENT_ID_ALERT and the child's phone number.
- **Alert webhook**: every alert, daily summary and weekly digest is POSTed as JSON to
  ALERT_WEBHOOK_URL, so it can be forwarded to WhatsApp, email or Slack with Make, Zapier or n8n.

Delivery runs in a background thread so it never delays call processing, and the outcome is written
back on the alert so the app can show it.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import httpx

from . import bolna
from .config import settings
from .db import session_scope
from .models import Alert, Call, CallAnalysis, Family, Parent

log = logging.getLogger(__name__)


def _post_webhook(payload: dict[str, Any]) -> str:
    """Returns '' on success, else an error message."""
    if not settings.ALERT_WEBHOOK_URL:
        return "no webhook"
    try:
        with httpx.Client(timeout=20) as c:
            r = c.post(settings.ALERT_WEBHOOK_URL, json=payload)
        return "" if r.status_code < 400 else f"webhook HTTP {r.status_code}"
    except httpx.HTTPError as exc:
        return f"webhook unreachable: {exc}"


def _alert_payload(alert: Alert, parent: Parent, family: Family | None) -> dict[str, Any]:
    return {
        "event": "alert",
        "kind": alert.kind,
        "title": alert.title,
        "reason": alert.reason,
        "talking_points": alert.talking_points,
        "parent": {"name": parent.name, "address_term": parent.address_term, "phone": parent.phone},
        "child": {"name": family.child_name if family else "", "phone": family.child_phone if family else ""},
        "created_at": alert.created_at.isoformat(),
    }


def _deliver(alert_id: int, mid_call: bool) -> None:
    with session_scope() as session:
        alert = session.get(Alert, alert_id)
        if alert is None:
            return
        parent = session.get(Parent, alert.parent_id)
        family = session.get(Family, parent.family_id) if parent else None
        if parent is None or family is None or alert.kind not in (family.notify_kinds or []):
            return
        done: list[str] = []
        errors: list[str] = []

        # 1) Saath phones the child. Skipped for an urgent alert raised mid-call when the agent is
        #    transferring the parent to the child: the child is being connected directly.
        src = session.get(Call, alert.call_id) if alert.call_id else None
        was_transferred = bool(src and src.transferred)  # she was already connected to the child live
        skip_call = was_transferred or (mid_call and alert.kind == "urgent" and settings.TRANSFER_ON_EMERGENCY)

        def _digits(x: str) -> str:
            return "".join(ch for ch in str(x) if ch.isdigit())[-10:]

        # Never ring her own phone, and never ring the same number twice.
        taken = {_digits(parent.phone)}
        child_ok = bool(family.child_phone) and _digits(family.child_phone) not in taken
        if child_ok:
            taken.add(_digits(family.child_phone))
        if settings.BOLNA_AGENT_ID_ALERT and settings.bolna_enabled and child_ok and not skip_call:
            try:
                bolna.place_call(settings.BOLNA_AGENT_ID_ALERT, family.child_phone, {
                    "child_name": family.child_name,
                    "address_term": parent.address_term,
                    "parent_name": parent.name,
                    "parent_phone": parent.phone,
                    "recipient_role": "family",
                    "family_name": family.child_name,
                    "alert_kind": alert.kind,
                    "alert_title": alert.title,
                    "alert_reason": alert.reason,
                    "talking_points": "; ".join(alert.talking_points) or "none",
                    "timezone": settings.TIMEZONE,
                })
                done.append("Saath called you")
            except bolna.BolnaError as exc:
                errors.append(f"Call to you failed: {exc}")
        elif skip_call and child_ok:
            done.append("Saath connected her to you")

        # 1b) Neighbours and relatives on ordinary phone numbers: urgent alerts and SOS calls only, and never
        #     for sample data. Each gets the same alert agent, told they are a neighbour so it asks them to go and check on her.
        if alert.kind in ("urgent", "sos") and settings.BOLNA_AGENT_ID_ALERT and settings.bolna_enabled:
            for n in (family.neighbours or []):
                if _digits(n.get("phone", "")) in taken:
                    continue
                taken.add(_digits(n.get("phone", "")))
                try:
                    bolna.place_call(settings.BOLNA_AGENT_ID_ALERT, n["phone"], {
                        "child_name": n.get("name") or "there",
                        "recipient_role": "neighbour",
                        "family_name": family.child_name,
                        "address_term": parent.address_term,
                        "parent_name": parent.name,
                        "parent_phone": parent.phone,
                        "alert_kind": alert.kind,
                        "alert_title": alert.title,
                        "alert_reason": f"{alert.reason} {family.child_name} has been told as well.",
                        "talking_points": "go and check on her in person if you can; call her now",
                        "timezone": settings.TIMEZONE,
                    })
                    done.append(f"Saath called {n.get('name') or 'a neighbour'}")
                except bolna.BolnaError as exc:
                    errors.append(f"Call to {n.get('name') or 'neighbour'} failed: {exc}")

        # 2) Webhook (WhatsApp, email, Slack via your automation)
        if settings.ALERT_WEBHOOK_URL:
            err = _post_webhook(_alert_payload(alert, parent, family))
            (errors if err else done).append(err or "Sent to your alert webhook")

        alert.notified = ", ".join(done)
        alert.notify_error = "; ".join(errors)[:500]
        session.add(alert)
        session.commit()


def notify_alert(alert_id: int, *, mid_call: bool = False) -> None:
    threading.Thread(target=_deliver, args=(alert_id, mid_call), daemon=True).start()


def send_daily_summary(call_id: int) -> None:
    """POST a completed call's summary to the webhook (the child's daily update)."""
    if not settings.ALERT_WEBHOOK_URL:
        return

    def run() -> None:
        with session_scope() as session:
            call = session.get(Call, call_id)
            a = session.get(CallAnalysis, call_id)
            if call is None or a is None:
                return
            parent = session.get(Parent, call.parent_id)
            _post_webhook({
                "event": "daily_summary",
                "parent": {"name": parent.name, "address_term": parent.address_term},
                "headline": a.headline,
                "summary": a.summary,
                "mood_score": a.mood_score,
                "said_fine_sounded_low": a.mismatch,
                "meals": a.meals,
                "medicines": a.meds,
                "reply_to_you": a.reply_to_child,
                "call_at": call.scheduled_at.isoformat(),
            })

    threading.Thread(target=run, daemon=True).start()


def send_weekly_digest(payload: dict[str, Any]) -> str:
    return _post_webhook({"event": "weekly_digest", **payload})
