"""Ask every model every verified question, grade the replies, save everything.

Usage: uv run python run.py --models fake-old,fake-new [--repeats 3]

Refuses to run if the answer key fails verify.py. Refuses to finish if the number of
saved results does not equal questions x models x repeats.
Results go to runs.db (SQLite) - the history the gate will read.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

import yaml

import verify
from answer import build_prompt, grade
from models import get_model
from retrieve import Index

ROOT = Path(__file__).parent
DB = ROOT / "runs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, models TEXT, repeats INTEGER,
  questions INTEGER, ground_truth_sha256 TEXT);
CREATE TABLE IF NOT EXISTS results (
  run_id INTEGER, model TEXT, qid TEXT, rep INTEGER, verdict TEXT, detail TEXT,
  raw_value TEXT, unit TEXT, source_quote TEXT, page INTEGER, reply TEXT,
  shown_pages TEXT, official_page_shown INTEGER, seconds REAL);
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True, help="comma-separated, e.g. fake-old,fake-new")
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()
    model_names = [m.strip() for m in args.models.split(",") if m.strip()]

    print("Checking the answer key first...")
    if verify.main() != 0:
        print("\nREFUSED - answer key does not pass verify.py. No model was asked anything.")
        return 1

    gt_bytes = (ROOT / "ground_truth.yaml").read_bytes()
    entries = [e for e in yaml.safe_load(gt_bytes) if e["verified"]]
    manifest = json.loads((ROOT / "corpus" / "manifest.json").read_text())
    models = [get_model(n) for n in model_names]

    db = sqlite3.connect(DB)
    db.executescript(SCHEMA)
    cur = db.execute(
        "INSERT INTO runs (started_at, models, repeats, questions, ground_truth_sha256) VALUES (?,?,?,?,?)",
        (datetime.datetime.now().isoformat(timespec="seconds"), ",".join(model_names), args.repeats,
         len(entries), hashlib.sha256(gt_bytes).hexdigest()))
    run_id = cur.lastrowid

    indexes = {}
    print(f"\nRun {run_id}: {len(entries)} questions x {len(models)} models x {args.repeats} repeats "
          f"= {len(entries) * len(models) * args.repeats} asks\n")
    for e in entries:
        idx = indexes.setdefault(e["doc"], Index(e["doc"]))
        shown = {p: idx.text[p] for p in idx.top(e["question"])}  # SAME pages for every model
        messages = build_prompt(e["question"], shown)
        for m in models:
            for rep in range(1, args.repeats + 1):
                t0 = time.time()
                try:
                    reply = m.ask(messages)
                    g = grade(e, reply, shown, manifest[e["doc"]]["locale"])
                except Exception as ex:   # a failed CALL is recorded, never silently skipped
                    reply = ""
                    g = {"verdict": "error", "detail": str(ex)[:300], "reply": None}
                secs = time.time() - t0
                r = g["reply"] or {}
                db.execute("INSERT INTO results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    run_id, m.name, e["id"], rep, g["verdict"], g["detail"],
                    r.get("raw_value"), r.get("unit"), r.get("source_quote"), r.get("page"),
                    reply, json.dumps(sorted(shown)), int(e["page"] in shown), round(secs, 3)))
        db.commit()
        print(f"  {e['id']} done", flush=True)

    expected = len(entries) * len(models) * args.repeats
    saved = db.execute("SELECT COUNT(*) FROM results WHERE run_id=?", (run_id,)).fetchone()[0]
    if saved != expected:
        print(f"\nREFUSED - expected {expected} saved results, found {saved}. Run {run_id} is incomplete.")
        return 1

    print(f"Run {run_id} complete: {saved} results saved to runs.db\n")
    for m in model_names:
        rows = db.execute(
            "SELECT qid, SUM(verdict='pass'), COUNT(*) FROM results WHERE run_id=? AND model=? GROUP BY qid",
            (run_id, m)).fetchall()
        stable = sum(1 for _, p, n in rows if p == n)
        flaky = sum(1 for _, p, n in rows if 0 < p < n)
        never = sum(1 for _, p, n in rows if p == 0)
        print(f"  {m:12}  right every time: {stable:2}   sometimes: {flaky:2}   never: {never:2}   (of {len(rows)})")
        for qid, p, n in rows:
            if p < n:
                v = db.execute("SELECT verdict, detail FROM results WHERE run_id=? AND model=? AND qid=? AND verdict!='pass' LIMIT 1",
                               (run_id, m, qid)).fetchone()
                print(f"      {qid}  {p}/{n} pass   {v[0]}: {v[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
