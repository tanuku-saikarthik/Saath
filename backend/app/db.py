from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine, select

from .config import settings

log = logging.getLogger(__name__)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {},
)


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, dict)):
        value = json.dumps(value)
    return "'" + str(value).replace("'", "''") + "'"


def _field_default(model: type[SQLModel], name: str) -> Any:
    info = model.model_fields.get(name)
    if info is None:
        return None
    if info.default_factory is not None:
        return info.default_factory()
    default = info.default
    return None if repr(default) == "PydanticUndefined" else default


def migrate() -> list[str]:
    """Add columns that newer versions of the models define but an existing SQLite file lacks.

    Existing rows get the field's default, so code that expects lists or strings keeps working.
    """
    added: list[str] = []
    insp = inspect(engine)
    models = {m.__tablename__: m for m in SQLModel.__subclasses__() if getattr(m, "__tablename__", None)}
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                coltype = col.type.compile(dialect=engine.dialect)
                default = _field_default(models[table.name], col.name) if table.name in models else None
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype} DEFAULT {_sql_literal(default)}'))
                added.append(f"{table.name}.{col.name}")
    if added:
        log.info("Database upgraded, added columns: %s", ", ".join(added))
    if "call_analysis.prosody" in added:
        _enable_new_alert_kinds(["sos", "voice"])
    return added


def _enable_new_alert_kinds(kinds: list[str]) -> None:
    """A database from before the SOS line and voice signals: switch those alerts on for each family,
    as a new family would have them."""
    from .models import Family

    with Session(engine) as session:
        for fam in session.exec(select(Family)).all():
            have = list(fam.notify_kinds or [])
            fam.notify_kinds = have + [k for k in kinds if k not in have]
            session.add(fam)
        session.commit()


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(engine)
    migrate()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
