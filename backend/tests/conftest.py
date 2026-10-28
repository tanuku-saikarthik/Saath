"""Each test session gets its own throwaway database and no external services."""
import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="saath_test_"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_tmp / 'test.db'}",
    "DATA_DIR": str(_tmp / "data"),
    "ENABLE_SCHEDULER": "false",
    "LLM_API_KEY": "",
    "SARVAM_API_KEY": "",
    "LLM_BASE_URL": "https://api.openai.com/v1",
    "BOLNA_API_KEY": "",
    "ALERT_WEBHOOK_URL": "",
    "OPENAI_API_KEY": "",
    "TOOL_TOKEN": "",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.db import engine, init_db  # noqa: E402
from app.seed import reset  # noqa: E402

init_db()


@pytest.fixture()
def session():
    with Session(engine) as s:
        reset(s)
        yield s
        reset(s)
