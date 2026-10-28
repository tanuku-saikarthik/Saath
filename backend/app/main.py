"""Saath backend. Run: uvicorn app.main:app --reload --port 8000 (from saath/backend)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import router
from .auth import require_login, router as auth_router
from .calls import scheduler, start_scheduler
from .config import settings
from .db import init_db
from .her import router as her_router
from .inbound import router as inbound_router
from .testcall import router as testcall_router
from .tools import router as tools_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if settings.AUTO_SEED:
        try:
            from .seed import seed
            seed(False)  # no-op when a parent already exists
        except Exception:  # never block startup
            logging.getLogger(__name__).exception("Auto-seed failed")
    start_scheduler()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Saath", version="0.1.0", lifespan=lifespan)
app.middleware("http")(require_login)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(router)
app.include_router(testcall_router)
app.include_router(tools_router)
app.include_router(inbound_router)
app.include_router(her_router)

# One-service hosting: serve the built family app (web/dist) from the same server.
WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
