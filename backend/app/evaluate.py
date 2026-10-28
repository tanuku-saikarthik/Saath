"""Evaluate the words pipeline on scripted Telugu and Hindi calls with known answers.

    python -m app.evaluate                # uses the LLM configured in .env
    python -m app.evaluate --limit 5      # quick check

Writes results/eval-<model>-<time>.json and prints a summary. Every number comes from this run;
nothing is hand-entered. The cases are scripted, not real calls, so the results say how well the
scoring reads clear examples, not how it performs on real parents.

What it checks per case (only the fields a case states):
- emergency: caught or not, split by who caught it (the LLM, the keyword safety net, or both)
- claimed_fine: did it notice she said she was fine
- valence: right sign (pos > 0, neg < 0)
- meds: each medicine's status exactly (taken / missed / unclear / not_discussed)
- dinner: the meal status exactly
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .config import BACKEND_ROOT, settings
from .pipeline.text_scoring import score_transcript

CASES = BACKEND_ROOT / "eval" / "cases.jsonl"
RESULTS = BACKEND_ROOT / "results"


def check(case: dict, r: dict) -> dict:
    exp = case["expect"]
    got: dict = {}
    if "emergency" in exp:
        got["emergency"] = r["emergency"] == exp["emergency"]
    if "claimed_fine" in exp:
        got["claimed_fine"] = r["claimed_fine"] == exp["claimed_fine"]
    if "valence" in exp:
        got["valence"] = r["valence"] > 0 if exp["valence"] == "pos" else r["valence"] < 0
    for name, status in exp.get("meds", {}).items():
        found = next((m["status"] for m in r["meds"] if m["name"].lower() == name.lower()), "not_discussed")
        got[f"med:{name}"] = found == status
    if "dinner" in exp:
        got["dinner"] = r["meals"].get("dinner") == exp["dinner"]
    return got


def summarise(rows: list[dict]) -> dict:
    by_field: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        for field, ok in row["checks"].items():
            key = "meds" if field.startswith("med:") else field
            by_field[key][row["lang"]].append(ok)
            by_field[key]["all"].append(ok)
    acc = {f: {lang: {"correct": sum(v), "total": len(v)} for lang, v in langs.items()} for f, langs in by_field.items()}

    emerg = [r for r in rows if r["expect"].get("emergency") is True]
    calm = [r for r in rows if r["expect"].get("emergency") is False]

    def caught(rs: list[dict], by: str) -> int:
        return sum(by in r["emergency_by"] for r in rs)

    return {
        "accuracy": acc,
        "emergency": {
            "real_emergencies": len(emerg),
            "caught_final": sum(r["result"]["emergency"] for r in emerg),
            "caught_by_llm": caught(emerg, "llm"),
            "caught_by_keyword": caught(emerg, "keyword"),
            "calm_calls": len(calm),
            "false_alarms_final": sum(r["result"]["emergency"] for r in calm),
            "false_alarms_by_llm": caught(calm, "llm"),
            "false_alarms_by_keyword": caught(calm, "keyword"),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    cases = [json.loads(l) for l in CASES.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        cases = cases[: args.limit]

    rows = []
    sources = set()
    t0 = time.time()
    for c in cases:
        r, source = score_transcript(c["transcript"], language=c["lang"], address_term="Amma" if c["lang"] == "te" else "Maa", medicines=c["medicines"])
        sources.add(source)
        checks = check(c, r)
        rows.append({"id": c["id"], "lang": c["lang"], "category": c["category"], "expect": c["expect"], "checks": checks,
                     "emergency_by": r.get("emergency_by", []), "result": {k: r[k] for k in ("emergency", "emergency_reason", "claimed_fine", "valence", "meds", "meals", "headline")}})
        bad = [k for k, ok in checks.items() if not ok]
        print(f"{c['id']:6} {c['category']:14} {'ok' if not bad else 'MISS ' + ', '.join(bad)}")

    summary = summarise(rows)
    model = settings.LLM_MODEL if sources == {"llm"} else "mock"
    out = {
        "model": model, "source": sorted(sources), "cases": len(rows), "seconds": round(time.time() - t0, 1),
        "run_at": datetime.now().isoformat(timespec="seconds"), "summary": summary, "rows": rows,
    }
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"eval-{model.replace('/', '_')}-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nModel: {model}   cases: {len(rows)}")
    if "mock" in sources:
        print("WARNING: no LLM reachable, these are keyword-mock results and mean nothing about the real pipeline.")
    for field, langs in summary["accuracy"].items():
        parts = [f"{lang} {v['correct']}/{v['total']}" for lang, v in langs.items()]
        print(f"  {field:13} " + "   ".join(parts))
    e = summary["emergency"]
    print(f"  emergencies caught {e['caught_final']}/{e['real_emergencies']} (LLM {e['caught_by_llm']}, keywords {e['caught_by_keyword']})")
    print(f"  false alarms       {e['false_alarms_final']}/{e['calm_calls']} (LLM {e['false_alarms_by_llm']}, keywords {e['false_alarms_by_keyword']})")
    print(f"\nSaved {path}")


if __name__ == "__main__":
    main()
