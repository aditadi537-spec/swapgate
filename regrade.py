"""Re-grade every saved reply with the CURRENT grader - without asking any model again.

Usage: uv run python regrade.py

Why: when the grading rules change (e.g. a new verdict), old runs were judged by the old
rules. Comparing runs judged by different rules is as meaningless as comparing runs with
different answer keys. Every reply is stored in runs.db, so we simply grade them again.
Server errors stay errors (there is no reply to grade).
"""
import json
import sqlite3
from collections import Counter
from pathlib import Path

import yaml

from answer import grade

ROOT = Path(__file__).parent


def main() -> None:
    db = sqlite3.connect(ROOT / "runs.db")
    entries = {e["id"]: e for e in yaml.safe_load((ROOT / "ground_truth.yaml").read_text(encoding="utf-8"))}
    manifest = json.loads((ROOT / "corpus" / "manifest.json").read_text())
    texts = {}
    changed = Counter()
    rows = db.execute("SELECT rowid, qid, verdict, reply, shown_pages FROM results").fetchall()
    for rowid, qid, old_verdict, reply, shown_json in rows:
        if old_verdict == "error":
            continue
        e = entries[qid]
        pages = texts.setdefault(e["doc"], {
            json.loads(l)["page"]: json.loads(l)["text"]
            for l in (ROOT / "corpus_text" / f"{e['doc']}.jsonl").read_text(encoding="utf-8").splitlines()})
        shown = {p: pages[p] for p in json.loads(shown_json)}
        g = grade(e, reply, shown, manifest[e["doc"]]["locale"])
        if g["verdict"] != old_verdict:
            changed[(qid, old_verdict, g["verdict"])] += 1
        # always refresh verdict AND explanation, so old wording never survives a rule change
        db.execute("UPDATE results SET verdict=?, detail=? WHERE rowid=?", (g["verdict"], g["detail"], rowid))
    db.commit()
    print(f"Re-graded {len(rows)} saved replies. Changed: {sum(changed.values())}")
    for (qid, old, new), n in sorted(changed.items()):
        print(f"  {qid}: {old} -> {new}  ({n}x)")


if __name__ == "__main__":
    main()
