"""Write the family app's demo snapshot (web/src/demo/snapshot.json) from the current database.

The app falls back to this snapshot when no backend is reachable. Run after `python -m app.seed --reset`:

    python -m app.snapshot
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from .main import app

OUT = Path(__file__).resolve().parents[2] / "web" / "src" / "demo" / "snapshot.json"


def main() -> None:
    client = TestClient(app)
    get = lambda path: client.get(path).json()  # noqa: E731
    snap: dict[str, object] = {}
    snap["/api/health"] = {"ok": True, "demo": True}  # sample data only: nothing about this machine's keys
    parents = get("/api/parents")
    snap["/api/parents"] = parents
    for p in parents:
        pid = p["id"]
        for path in (f"/api/parents/{pid}/overview", f"/api/parents/{pid}/trend?days=14", f"/api/parents/{pid}/calls?limit=30",
                     f"/api/parents/{pid}/alerts", f"/api/parents/{pid}/notes", f"/api/parents/{pid}/week"):
            snap[path] = get(path)
        for c in snap[f"/api/parents/{pid}/calls?limit=30"]:  # type: ignore[union-attr]
            snap[f"/api/calls/{c['id']}"] = get(f"/api/calls/{c['id']}")
    OUT.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Wrote {len(snap)} endpoints to {OUT}")


if __name__ == "__main__":
    main()
