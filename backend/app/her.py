"""'Saath for her': a tiny installable web page for her smartphone, paired with the family app.

Four big buttons: SOS (press and hold), call the child, talk to Saath, and "I'm fine today".
Phone calls stay the main thing; this page only adds a way for her to reach the family, and a text copy of messages.
"""
from __future__ import annotations

import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from .config import settings
from .db import get_session
from .models import Alert, Family, HerDevice, Note, PairCode, Parent, utcnow
from .notify import notify_alert

router = APIRouter()
STATIC = Path(__file__).resolve().parent / "her_static"
SOS_COOLDOWN = timedelta(seconds=60)
_attempts: dict[str, deque] = defaultdict(deque)


def _throttle(key: str, limit: int = 8, window: int = 60) -> None:
    q, now = _attempts[key], time.monotonic()
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Too many tries. Wait a minute.")
    q.append(now)


# ---------- family side ----------

@router.post("/api/parents/{parent_id}/pair-code")
def make_pair_code(parent_id: int, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    if not session.get(Parent, parent_id):
        raise HTTPException(404, "Parent not found")
    for old in session.exec(select(PairCode).where(PairCode.parent_id == parent_id, PairCode.used == False)).all():  # noqa: E712
        session.delete(old)
    code = f"{secrets.randbelow(10**6):06d}"
    session.add(PairCode(parent_id=parent_id, code=code, expires_at=utcnow() + timedelta(minutes=15)))
    session.commit()
    base = (settings.PUBLIC_BASE_URL or str(request.base_url)).rstrip("/")
    return {"code": code, "expires_in_minutes": 15, "link": f"{base}/her"}


@router.get("/api/parents/{parent_id}/her-phone")
def her_phone_status(parent_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    from .api import local
    devs = session.exec(select(HerDevice).where(HerDevice.parent_id == parent_id)).all()
    return {"paired": bool(devs), "devices": [
        {"id": d.id, "paired_at": local(d.created_at), "last_seen": local(d.last_seen_at),
         "last_fine": local(d.last_fine_at), "last_sos": local(d.last_sos_at)} for d in devs]}


@router.delete("/api/parents/{parent_id}/her-phone")
def unpair(parent_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    for d in session.exec(select(HerDevice).where(HerDevice.parent_id == parent_id)).all():
        session.delete(d)
    session.commit()
    return {"paired": False}


# ---------- her side ----------

def _device(x_her_token: str = Header(default=""), session: Session = Depends(get_session)) -> HerDevice:
    if x_her_token:
        for d in session.exec(select(HerDevice).where(HerDevice.token == x_her_token)).all():
            if hmac.compare_digest(d.token, x_her_token):
                d.last_seen_at = utcnow()
                session.add(d)
                session.commit()
                return d
    raise HTTPException(401, "This phone isn't paired.")


class PairIn(BaseModel):
    code: str


@router.post("/api/her/pair")
def pair(body: PairIn, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    _throttle(request.client.host if request.client else "x")
    row = session.exec(select(PairCode).where(PairCode.code == body.code.strip(), PairCode.used == False)).first()  # noqa: E712
    if not row or row.expires_at.replace(tzinfo=row.expires_at.tzinfo or utcnow().tzinfo) < utcnow():
        raise HTTPException(400, "That code didn't work. Ask for a new one.")
    row.used = True
    token = secrets.token_urlsafe(32)
    session.add(row)
    session.add(HerDevice(parent_id=row.parent_id, token=token, last_seen_at=utcnow()))
    session.commit()
    return {"token": token}


@router.get("/api/her/me")
def me(dev: HerDevice = Depends(_device), session: Session = Depends(get_session)) -> dict[str, Any]:
    p = session.get(Parent, dev.parent_id)
    fam = session.get(Family, p.family_id)
    note = session.exec(select(Note).where(Note.parent_id == p.id, Note.is_question == False).order_by(Note.created_at.desc())).first()  # noqa: E712
    return {
        "address_term": p.address_term, "language": p.language, "child_name": fam.child_name,
        "child_phone": fam.child_phone, "saath_number": settings.SOS_NUMBER,
        "message": note.text if note else "",
    }


@router.post("/api/her/fine")
def fine(dev: HerDevice = Depends(_device), session: Session = Depends(get_session)) -> dict[str, Any]:
    dev.last_fine_at = utcnow()
    session.add(dev)
    session.commit()
    return {"ok": True}


@router.post("/api/her/sos")
def sos(dev: HerDevice = Depends(_device), session: Session = Depends(get_session)) -> dict[str, Any]:
    now = utcnow()
    last = dev.last_sos_at
    if last and now - last.replace(tzinfo=last.tzinfo or now.tzinfo) < SOS_COOLDOWN:
        return {"ok": True, "repeat": True}
    p = session.get(Parent, dev.parent_id)
    dev.last_sos_at = now
    alert = Alert(
        parent_id=p.id, kind="urgent", title=f"{p.address_term} pressed SOS on her phone",
        reason="She pressed and held the SOS button on her phone.",
        talking_points=["Call her now", "If you can't reach her, ask a neighbour to check in"],
    )
    session.add(dev)
    session.add(alert)
    session.commit()
    notify_alert(alert.id)
    return {"ok": True}


# ---------- the page itself ----------

def _file(name: str, media: str) -> Response:
    f = STATIC / name
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type=media, headers={"Cache-Control": "no-cache"})


@router.get("/her")
def her_page() -> Response:
    return _file("index.html", "text/html")


@router.get("/her/manifest.webmanifest")
def her_manifest() -> Response:
    return _file("manifest.webmanifest", "application/manifest+json")


@router.get("/her/sw.js")
def her_sw() -> Response:
    f = STATIC / "sw.js"
    return FileResponse(f, media_type="text/javascript", headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/her"})


@router.get("/her/icon-{size}.png")
def her_icon(size: int) -> Response:
    if size not in (192, 512):
        raise HTTPException(404)
    return _file(f"icon-{size}.png", "image/png")
