"""SQLModel tables. One `Call` row per phone call; everything derived hangs off it."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


ALERT_KINDS = ["urgent", "sos", "drop", "recurring", "voice", "missed"]
# Calls that count toward her mood trend. Reminder calls are short and functional, so they don't.
MOOD_KINDS = ["daily", "retry", "inbound", "callback"]


class Family(SQLModel, table=True):
    __tablename__ = "families"
    id: Optional[int] = Field(default=None, primary_key=True)
    child_name: str
    child_phone: str = ""
    # Neighbours or relatives on ordinary phone numbers: Saath rings them too on an urgent alert or when she calls Saath for help
    neighbours: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    # Which alerts reach the child outside the app (a call from Saath and/or the alert webhook)
    notify_kinds: list[str] = Field(default_factory=lambda: list(ALERT_KINDS), sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class Parent(SQLModel, table=True):
    __tablename__ = "parents"
    id: Optional[int] = Field(default=None, primary_key=True)
    family_id: int = Field(foreign_key="families.id", index=True)
    name: str
    address_term: str  # what the child calls them: Amma, Nanna, Maa
    phone: str
    language: str = "te"  # "te" | "hi"
    call_time: str = "19:00"  # HH:MM, local time
    topics: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    consent_status: str = "pending"  # pending | granted | declined
    created_at: datetime = Field(default_factory=utcnow)


class Medicine(SQLModel, table=True):
    __tablename__ = "medicines"
    id: Optional[int] = Field(default=None, primary_key=True)
    parent_id: int = Field(foreign_key="parents.id", index=True)
    name: str
    timing: str = ""  # "morning", "after dinner", ...
    reminder_time: str = ""  # HH:MM local; empty = no reminder call


class Call(SQLModel, table=True):
    __tablename__ = "calls"
    id: Optional[int] = Field(default=None, primary_key=True)
    parent_id: int = Field(foreign_key="parents.id", index=True)
    bolna_execution_id: Optional[str] = Field(default=None, unique=True, index=True)
    # daily | intro | retry | reminder (medicine) | inbound (she called Saath) | callback (after her missed call)
    kind: str = "daily"
    attempt: int = 1
    scheduled_at: datetime = Field(default_factory=utcnow)
    # queued | in_progress | processing | completed | missed | failed
    status: str = "queued"
    bolna_status: str = ""
    duration_s: int = 0
    transcript: str = ""
    audio_path: str = ""
    is_seeded: bool = False
    note_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))  # child's messages sent with this call
    transferred: bool = False  # Saath connected the parent to the child live
    reminder_for: str = ""  # reminder calls: the medicine's name
    user_speaking_ms: int = 0  # from Bolna's call record, when present
    created_at: datetime = Field(default_factory=utcnow)
    processed_at: Optional[datetime] = None
    error: str = ""


class Note(SQLModel, table=True):
    """A message from the child that Saath passes on in the next call, with the parent's reply."""
    __tablename__ = "notes"
    id: Optional[int] = Field(default=None, primary_key=True)
    parent_id: int = Field(foreign_key="parents.id", index=True)
    text: str
    created_at: datetime = Field(default_factory=utcnow)
    call_id: Optional[int] = Field(default=None, foreign_key="calls.id")
    delivered_at: Optional[datetime] = None
    reply: str = ""
    is_question: bool = False


class CallAnalysis(SQLModel, table=True):
    __tablename__ = "call_analysis"
    call_id: int = Field(foreign_key="calls.id", primary_key=True)
    source: str = "llm"  # llm | mock | seed
    text_emotions: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    text_valence: float = 0.0
    arousal: float = 0.0
    claimed_fine: bool = False
    evidence: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    voice_probs: dict[str, float] = Field(default_factory=dict, sa_column=Column(JSON))
    voice_valence: Optional[float] = None
    voice_source: str = ""  # parent_channel | mixed | none
    voice_segments: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    mood_score: float = 0.0
    mismatch: bool = False
    meals: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    meds: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    worries: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    health_mentions: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    topics: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    open_threads: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    avoid_topics: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    emergency: bool = False
    emergency_reason: str = ""
    headline: str = ""
    summary: str = ""
    transcript_en: str = ""
    message_delivered: bool = False  # Saath passed on the child's message
    reply_to_child: str = ""
    consent: str = ""  # intro calls: yes | no | unclear
    # How she spoke (pipeline/prosody.py): pace, pauses, loudness, pitch movement. Wellness signal, not a diagnosis.
    prosody: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class Alert(SQLModel, table=True):
    __tablename__ = "alerts"
    id: Optional[int] = Field(default=None, primary_key=True)
    parent_id: int = Field(foreign_key="parents.id", index=True)
    call_id: Optional[int] = Field(default=None, foreign_key="calls.id")
    kind: str  # urgent | drop | recurring | missed
    title: str
    reason: str
    talking_points: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    seen_at: Optional[datetime] = None
    notified: str = ""  # how it reached the child, e.g. "Saath called you" or "Sent to your webhook"
    notify_error: str = ""


class CallContext(SQLModel, table=True):
    __tablename__ = "call_context"
    parent_id: int = Field(foreign_key="parents.id", primary_key=True)
    tone: str = "warm"  # warm | gentle
    open_threads: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    meds_to_check: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    avoid_topics: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    last_note: str = ""
    updated_at: datetime = Field(default_factory=utcnow)


class PairCode(SQLModel, table=True):
    """A one-time 6-digit code the child shows so her phone can be paired."""
    __tablename__ = "pair_codes"
    id: Optional[int] = Field(default=None, primary_key=True)
    parent_id: int = Field(foreign_key="parents.id", index=True)
    code: str = Field(index=True)
    expires_at: datetime
    used: bool = False


class HerDevice(SQLModel, table=True):
    """Her paired phone (the 'Saath for her' page). The token is the only credential it holds."""
    __tablename__ = "her_devices"
    id: Optional[int] = Field(default=None, primary_key=True)
    parent_id: int = Field(foreign_key="parents.id", index=True)
    token: str = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)
    last_seen_at: Optional[datetime] = None
    last_fine_at: Optional[datetime] = None
    last_sos_at: Optional[datetime] = None
