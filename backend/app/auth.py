"""One shared password for the family app (set APP_PASSWORD). Her phone page, Bolna webhooks and /api/health stay open:
they have their own checks (her paired token, the tool token) or hold no data."""
from __future__ import annotations

import hashlib
import hmac
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import settings

router = APIRouter(prefix="/api/auth")
COOKIE = "saath_auth"
OPEN_PREFIXES = ("/api/auth/", "/api/health", "/api/her/")
_tries: dict[str, deque] = defaultdict(deque)


def _token() -> str:
    return hmac.new(settings.APP_PASSWORD.encode(), b"saath-family-session-v1", hashlib.sha256).hexdigest()


def is_authed(request: Request) -> bool:
    if not settings.APP_PASSWORD:
        return True
    got = request.cookies.get(COOKIE, "")
    return bool(got) and hmac.compare_digest(got, _token())


async def require_login(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and not path.startswith(OPEN_PREFIXES) and request.method != "OPTIONS" and not is_authed(request):
        return JSONResponse({"detail": "Sign in first."}, status_code=401)
    return await call_next(request)


class LoginIn(BaseModel):
    password: str


@router.get("/status")
def status(request: Request) -> dict:
    return {"required": bool(settings.APP_PASSWORD), "authed": is_authed(request)}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response) -> dict:
    if not settings.APP_PASSWORD:
        return {"ok": True}
    q, now = _tries[request.client.host if request.client else "x"], time.monotonic()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= 8:
        raise HTTPException(429, "Too many tries. Wait a minute.")
    q.append(now)
    if not hmac.compare_digest(body.password.encode(), settings.APP_PASSWORD.encode()):
        raise HTTPException(401, "That password isn't right.")
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, _token(), max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax", secure=secure)
    return {"ok": True}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE)
    return {"ok": True}
