"""Placing calls, the daily scheduler, retries, and a polling fallback for when no webhook is reachable."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session, select

from . import bolna
from .config import settings
from .context import prepare_call
from .db import session_scope
from .models import Call, Medicine, Parent, utcnow
from .process import handle_execution, handle_missed, run_outcome

log = logging.getLogger(__name__)
TZ = ZoneInfo(settings.TIMEZONE)
scheduler = BackgroundScheduler(timezone=TZ)


def start_call(session: Session, parent: Parent, kind: str = "daily", attempt: int = 1, scheduled: bool = False,
               reminder_for: str = "") -> Call:
    """Create the Call row, then ask Bolna to dial. Errors are stored on the row, not raised.

    A scheduled call that can't be placed is treated like an unanswered one (retry, then a missed
    check-in alert), so a Bolna outage never silently skips an evening. A manual "Call now" that fails
    just shows the error.
    """
    call = Call(parent_id=parent.id, kind=kind, attempt=attempt, status="queued", scheduled_at=utcnow(), reminder_for=reminder_for)
    session.add(call)
    session.commit()
    session.refresh(call)
    failed = False
    try:
        data = prepare_call(session, parent, call)
        call.bolna_execution_id = bolna.place_call(settings.agent_id_for(parent.language), parent.phone, data)
    except bolna.BolnaError as exc:
        call.status = "failed"
        call.error = str(exc)
        failed = True
        log.warning("Could not place call for parent %s: %s", parent.id, exc)
    session.add(call)
    session.commit()
    session.refresh(call)
    if failed and scheduled and kind in ("daily", "retry"):
        handle_missed(call.id)
    return call


def _local_now() -> datetime:
    return datetime.now(TZ)


def _called_today(session: Session, parent_id: int) -> bool:
    local_midnight = _local_now().replace(hour=0, minute=0, second=0, microsecond=0)
    since_utc = local_midnight.astimezone(ZoneInfo("UTC"))
    return session.exec(
        select(Call).where(Call.parent_id == parent_id, Call.kind.in_(["daily", "retry"]), Call.scheduled_at >= since_utc, Call.is_seeded == False)  # noqa: E712
    ).first() is not None


def _reminded_today(session: Session, parent_id: int, medicine: str) -> bool:
    since_utc = _local_now().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(ZoneInfo("UTC"))
    return session.exec(
        select(Call).where(Call.parent_id == parent_id, Call.kind == "reminder", Call.reminder_for == medicine,
                           Call.scheduled_at >= since_utc, Call.is_seeded == False)  # noqa: E712
    ).first() is not None


def daily_tick() -> None:
    """Every minute: dial parents whose call time is now and who haven't been called today, and place
    medicine reminder calls that are due."""
    if not settings.bolna_enabled:
        return
    hhmm = _local_now().strftime("%H:%M")
    with session_scope() as session:
        for parent in session.exec(select(Parent).where(Parent.consent_status == "granted", Parent.call_time == hhmm)).all():
            if not _called_today(session, parent.id):
                start_call(session, parent, "daily", 1, scheduled=True)
        for med in session.exec(select(Medicine).where(Medicine.reminder_time == hhmm)).all():
            parent = session.get(Parent, med.parent_id)
            if parent and parent.consent_status == "granted" and not _reminded_today(session, parent.id, med.name):
                start_call(session, parent, "reminder", 1, scheduled=True, reminder_for=med.name)


def call_back(parent_id: int) -> None:
    """She called Saath and the line dropped before she spoke: ring her straight back."""
    with session_scope() as session:
        parent = session.get(Parent, parent_id)
        if parent:
            call = start_call(session, parent, "callback", 1)
            if call.status == "failed":
                handle_missed(call.id)


def _run_retry(parent_id: int) -> None:
    with session_scope() as session:
        parent = session.get(Parent, parent_id)
        if parent:
            start_call(session, parent, "retry", 2, scheduled=True)


CATCH_UP_HOURS = 2


def recover_after_restart() -> None:
    """Scheduled jobs live in memory. After a restart, redo today's work the server missed:
    place a call whose time passed while it was down (within CATCH_UP_HOURS), and re-schedule a
    retry that was pending."""
    if not settings.bolna_enabled:
        return
    now = _local_now()
    midnight_utc = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(ZoneInfo("UTC"))
    with session_scope() as session:
        for parent in session.exec(select(Parent).where(Parent.consent_status == "granted")).all():
            today = session.exec(
                select(Call).where(Call.parent_id == parent.id, Call.kind.in_(["daily", "retry"]), Call.scheduled_at >= midnight_utc, Call.is_seeded == False)  # noqa: E712
            ).all()
            hh, mm = (int(x) for x in parent.call_time.split(":"))
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if not today and due <= now <= due + timedelta(hours=CATCH_UP_HOURS):
                log.info("Catching up on today's call for parent %s", parent.id)
                start_call(session, parent, "daily", 1, scheduled=True)
            elif today and not any(c.kind == "retry" for c in today) and all(c.status in ("missed", "failed") for c in today):
                schedule_retry(parent.id, minutes=1)


def schedule_retry(parent_id: int, minutes: int | None = None) -> None:
    run_at = _local_now() + timedelta(minutes=settings.RETRY_MINUTES if minutes is None else minutes)
    if scheduler.running:
        scheduler.add_job(_run_retry, "date", run_date=run_at, args=[parent_id], id=f"retry-{parent_id}", replace_existing=True)
        log.info("Retry for parent %s at %s", parent_id, run_at)


def poll_open_calls() -> None:
    """Fallback for local dev without a public webhook: poll Bolna for calls still open."""
    if not settings.bolna_enabled:
        return
    cutoff = utcnow() - timedelta(seconds=30)
    with session_scope() as session:
        open_calls = session.exec(
            select(Call).where(Call.status.in_(["queued", "in_progress"]), Call.bolna_execution_id != None, Call.scheduled_at <= cutoff)  # noqa: E711
        ).all()
        ids = [c.bolna_execution_id for c in open_calls]
    for exec_id in ids:
        try:
            run_outcome(handle_execution(bolna.get_execution(exec_id)))
        except bolna.BolnaError as exc:
            log.warning("Polling %s failed: %s", exec_id, exc)


def start_scheduler() -> None:
    if scheduler.running or not settings.ENABLE_SCHEDULER:
        return
    scheduler.add_job(daily_tick, "cron", second=5, id="daily-tick", replace_existing=True)
    scheduler.add_job(poll_open_calls, "interval", seconds=30, id="poll-open", replace_existing=True)
    scheduler.add_job(weekly_digest_job, "cron", day_of_week="sun", hour=20, minute=30, id="weekly-digest", replace_existing=True)
    scheduler.start()
    recover_after_restart()


def weekly_digest_job() -> None:
    """Sunday evening: send each family the week's digest through the alert webhook."""
    if not settings.ALERT_WEBHOOK_URL:
        return
    from .notify import send_weekly_digest
    from .week import compute_week

    with session_scope() as session:
        for parent in session.exec(select(Parent)).all():
            send_weekly_digest(compute_week(session, parent))
