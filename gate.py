"""The gate: decide whether a model change is safe, from saved run results.

Usage:
  uv run python gate.py swap <old model> <new model>   e.g. swap ollama:qwen3:8b ollama:qwen3.5:9b
  uv run python gate.py history <model>                latest run of a model vs its previous run

Each question gets a status per model from its repeated attempts:
  reliable      right every time
  unreliable    right sometimes, wrong sometimes
  fails         wrong every time
  inconclusive  at least one attempt was a server/call error - cannot judge, re-run it

Rule: every question the OLD model answers reliably must still be answered reliably by the NEW.
  new fails or is unreliable on it  -> regression
  new inconclusive on it            -> cannot decide

Exit code: 0 = approved, 1 = REFUSED (regressions), 2 = inconclusive.
Also refuses to compare at all if the answer key changed between the two runs.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).parent / "runs.db"
APPROVED, REFUSED, INCONCLUSIVE = 0, 1, 2


def latest_runs(db, model: str, n: int = 1) -> list[int]:
    rows = db.execute("SELECT DISTINCT run_id FROM results WHERE model=? ORDER BY run_id DESC LIMIT ?",
                      (model, n)).fetchall()
    return [r[0] for r in rows]


def statuses(db, run_id: int, model: str) -> dict[str, dict]:
    out = {}
    rows = db.execute("SELECT qid, verdict, raw_value, unit, detail FROM results "
                      "WHERE run_id=? AND model=? ORDER BY qid, rep", (run_id, model)).fetchall()
    for qid, verdict, raw, unit, detail in rows:
        q = out.setdefault(qid, {"verdicts": [], "examples": []})
        q["verdicts"].append(verdict)
        if verdict != "pass":
            q["examples"].append((verdict, raw, unit, detail))
    for q in out.values():
        v = q["verdicts"]
        if "error" in v:
            q["status"] = "inconclusive"
        elif all(x == "pass" for x in v):
            q["status"] = "reliable"
        elif any(x == "pass" for x in v):
            q["status"] = "unreliable"
        else:
            q["status"] = "fails"
        q["score"] = f"{v.count('pass')}/{len(v)}"
    return out


def decide(old: dict, new: dict) -> dict:
    """THE rule, in one place (gate and report both use it, so they can never disagree):
    every question the old model answers reliably must still be answered reliably."""
    out = {"kept": [], "regressions": [], "unknown": [], "improvements": []}
    for qid in sorted(old):
        o, n = old[qid]["status"], new[qid]["status"]
        if o == "reliable":
            key = "kept" if n == "reliable" else "unknown" if n == "inconclusive" else "regressions"
            out[key].append(qid)
        elif n == "reliable":
            out["improvements"].append(qid)
    return out


def compare(db, old_model: str, old_run: int, new_model: str, new_run: int, label: str) -> int:
    sha = dict(db.execute("SELECT run_id, ground_truth_sha256 FROM runs WHERE run_id IN (?,?)",
                          (old_run, new_run)).fetchall())
    if sha.get(old_run) != sha.get(new_run):
        print(f"REFUSED TO COMPARE - the answer key changed between run {old_run} and run {new_run}.")
        print("Results graded against different answer keys are not comparable. Re-run both models.")
        return REFUSED

    old, new = statuses(db, old_run, old_model), statuses(db, new_run, new_model)
    if set(old) != set(new):
        print(f"REFUSED TO COMPARE - the runs contain different questions "
              f"(only in old: {sorted(set(old) - set(new))}, only in new: {sorted(set(new) - set(old))}).")
        return REFUSED

    d = decide(old, new)
    regressions, unknown, improvements, kept = d["regressions"], d["unknown"], d["improvements"], len(d["kept"])

    print(f"{label}\n  old: {old_model} (run {old_run})   new: {new_model} (run {new_run})\n")
    print(f"  still reliable: {kept}   regressions: {len(regressions)}   "
          f"inconclusive: {len(unknown)}   improvements: {len(improvements)}\n")
    for qid in regressions:
        n = new[qid]
        verdict, raw, unit, detail = n["examples"][0]
        what = "now FAILS" if n["status"] == "fails" else "now UNRELIABLE"
        print(f"  ✗ {qid}  {what} ({n['score']} right, was {old[qid]['score']})")
        print(f"       new model said: {raw!r} {unit or ''}  ->  {verdict}: {detail}")
    for qid in unknown:
        print(f"  ? {qid}  new model had call errors - re-run before deciding")
    for qid in improvements:
        print(f"  + {qid}  now reliable (was {old[qid]['status']}, {old[qid]['score']})")

    if regressions:
        print(f"\nSWAP REFUSED - {len(regressions)} question(s) the old model answered reliably "
              f"are no longer answered reliably.")
        return REFUSED
    if unknown:
        print("\nINCONCLUSIVE - no regressions found, but some answers could not be judged. Re-run them.")
        return INCONCLUSIVE
    print("\nSWAP APPROVED - everything the old model answered reliably, the new model still does.")
    return APPROVED


def main() -> int:
    if not DB.exists():
        print("No runs.db yet - run run.py first."); return INCONCLUSIVE
    db = sqlite3.connect(DB)
    args = sys.argv[1:]
    if len(args) == 3 and args[0] == "swap":
        old_model, new_model = args[1], args[2]
        o, n = latest_runs(db, old_model), latest_runs(db, new_model)
        if not o or not n:
            print(f"No saved results for {old_model if not o else new_model}. Run it first.")
            return INCONCLUSIVE
        return compare(db, old_model, o[0], new_model, n[0], "MODEL SWAP CHECK")
    if len(args) == 2 and args[0] == "history":
        runs = latest_runs(db, args[1], 2)
        if len(runs) < 2:
            print(f"{args[1]} has only {len(runs)} saved run(s); history needs 2.")
            return INCONCLUSIVE
        return compare(db, args[1], runs[1], args[1], runs[0], "SAME-MODEL HISTORY CHECK")
    print(__doc__)
    return INCONCLUSIVE


if __name__ == "__main__":
    sys.exit(main())
