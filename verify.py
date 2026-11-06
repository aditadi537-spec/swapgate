"""Check the answer key against the source documents BEFORE any model is graded.

Usage: uv run python verify.py

For every entry in ground_truth.yaml this checks that:
  1. all required fields are present and every id is unique
  2. the cited page exists in that document
  3. the quote really appears on the cited page (and says where it does appear if not)
  4. the answer's number appears inside the quote (catches typos in the answer)
  5. the grader can parse the answer
  6. answer and quote were written as quoted text, so YAML did not silently convert them

Any problem -> prints REFUSED and exits with code 1. Unverified entries are listed
as pending: they are checked, but never used to grade a model.
"""
import json
import re
import sys
from pathlib import Path

import yaml

from normalize import Unparseable, parse_quantity

ROOT = Path(__file__).parent
REQUIRED = ["id", "doc", "question", "type", "answer", "page", "quote", "verified"]
NUM = re.compile(r"\d[\d.,']*\d|\d")


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def load_pages(doc_id: str) -> dict[int, str]:
    path = ROOT / "corpus_text" / f"{doc_id}.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return {r["page"]: squash(r["text"]) for r in rows}


def check_entry(e: dict, manifest: dict, pages_cache: dict) -> list[str]:
    errs = [f"missing field '{f}'" for f in REQUIRED if f not in e]
    if errs:
        return errs

    for f in ("answer", "quote", "question"):
        if not isinstance(e[f], str):
            errs.append(f"'{f}' must be in quotes \"...\" - YAML turned it into {type(e[f]).__name__} {e[f]!r}")
    if not isinstance(e["verified"], bool):
        errs.append("'verified' must be true or false")
    if e["type"] not in ("quantity", "text"):
        errs.append(f"type must be quantity or text, got {e['type']!r}")
    if e["doc"] not in manifest:
        return errs + [f"unknown doc {e['doc']!r}; known: {sorted(manifest)}"]
    if errs:
        return errs

    pages = pages_cache.setdefault(e["doc"], load_pages(e["doc"]))
    n_pages = manifest[e["doc"]]["pages"]
    if not isinstance(e["page"], int) or not 1 <= e["page"] <= n_pages:
        return [f"page {e['page']!r} does not exist ({e['doc']} has pages 1-{n_pages})"]

    # Compare with ALL spaces removed: PDF text often has "$ 416,161" where a copy
    # from Preview gives "$416,161". Spacing differences must not fail a correct quote.
    quote = squash(e["quote"]).replace(" ", "")
    if quote not in pages[e["page"]].replace(" ", ""):
        elsewhere = [p for p, t in pages.items() if quote in t.replace(" ", "")]
        hint = f" It IS on page(s) {elsewhere[:10]}." if elsewhere else " It is on no page - check for typos."
        errs.append(f"quote not found on page {e['page']}.{hint}")

    if e["type"] == "quantity":
        try:
            parse_quantity(e["answer"], manifest[e["doc"]]["locale"])
        except Unparseable as ex:
            errs.append(f"grader cannot read answer {e['answer']!r}: {ex}")
        nums = NUM.findall(e["answer"])
        if nums and nums[0] not in e["quote"]:
            errs.append(f"answer number {nums[0]} does not appear in the quote - typo in one of them?")
    else:
        aliases = e.get("aliases")
        if not isinstance(aliases, list) or not aliases:
            errs.append("text answers need an 'aliases' list of accepted spellings")
        elif squash(e["answer"]).replace(" ", "") not in quote and not any(
                squash(a).replace(" ", "") in quote for a in aliases):
            errs.append("neither the answer nor any alias appears in the quote")
    return errs


def main() -> int:
    manifest = json.loads((ROOT / "corpus" / "manifest.json").read_text())
    try:
        entries = yaml.safe_load((ROOT / "ground_truth.yaml").read_text(encoding="utf-8")) or []
    except yaml.YAMLError as ex:
        mark = getattr(ex, "problem_mark", None)
        where = f" near line {mark.line + 1}" if mark else ""
        print(f"REFUSED - ground_truth.yaml is not valid YAML{where}.")
        print("  Most common causes: a line inside an entry not starting with exactly 2 spaces,")
        print("  a line break inside quoted text, or curly quotes instead of straight ones.")
        print(f"  (details: {getattr(ex, 'problem', ex)})")
        return 1

    problems, pending, ok, seen, cache = {}, [], [], set(), {}
    seen_q, seen_fact = {}, {}
    for i, e in enumerate(entries, start=1):
        eid = e.get("id", f"entry #{i}") if isinstance(e, dict) else f"entry #{i}"
        if not isinstance(e, dict):
            problems[eid] = ["not a valid entry - check indentation"]
            continue
        errs = check_entry(e, manifest, cache)
        if eid in seen:
            errs.insert(0, "duplicate id")
        seen.add(eid)
        # Same question, or same answer on the same page = the same fact counted twice.
        q_key = squash(e.get("question", ""))
        fact_key = (e.get("doc"), e.get("page"), squash(e.get("answer", "")))
        if q_key in seen_q:
            errs.insert(0, f"same question as {seen_q[q_key]} - did the up-arrow repeat an old answer?")
        elif fact_key in seen_fact:
            errs.insert(0, f"same answer on the same page as {seen_fact[fact_key]} - duplicate fact?")
        seen_q.setdefault(q_key, eid)
        seen_fact.setdefault(fact_key, eid)
        if errs:
            problems[eid] = errs
        elif e["verified"]:
            ok.append(eid)
        else:
            pending.append(eid)

    print(f"{len(entries)} entries: {len(ok)} verified, {len(pending)} pending, {len(problems)} with problems\n")
    for eid, errs in problems.items():
        for err in errs:
            print(f"  ✗ {eid}: {err}")
    if pending:
        print(f"  … pending (checked, but not yet confirmed by you): {', '.join(pending)}")
    if problems:
        print("\nREFUSED - fix the problems above. No model will be graded against this answer key.")
        return 1
    print(f"\nOK - {len(ok)} answers usable for grading.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
