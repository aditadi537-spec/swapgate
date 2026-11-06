"""Add one ground-truth entry by answering questions - no YAML typing needed.

Usage: uv run python add.py

It asks for each field, runs every verify.py check on the entry, and only
appends it to ground_truth.yaml if all checks pass. Nothing is saved otherwise.
"""
import json
import sys
from pathlib import Path

import yaml

from verify import check_entry

ROOT = Path(__file__).parent
GT = ROOT / "ground_truth.yaml"


def ask(prompt: str, allow_empty: bool = False) -> str:
    while True:
        value = input(f"{prompt}: ").strip()
        if value or allow_empty:
            return value
        print("  (cannot be empty)")


def main() -> int:
    manifest = json.loads((ROOT / "corpus" / "manifest.json").read_text())
    entries = yaml.safe_load(GT.read_text(encoding="utf-8")) or []
    next_id = f"Q{len(entries) + 1:02d}"
    docs = sorted(manifest)

    print(f"\nNew entry {next_id}. Press Ctrl+C at any time to cancel.\n")
    for i, d in enumerate(docs, 1):
        print(f"  {i}. {d}")
    while True:
        pick = ask("Which report? (number)")
        if pick.isdigit() and 1 <= int(pick) <= len(docs):
            doc = docs[int(pick) - 1]
            break
        print("  type one of the numbers above")

    question = ask("Question (exactly as it will be asked to every model)")
    kind = ""
    while kind not in ("quantity", "text"):
        reply = ask("Type: type the letter q (a number with unit) or t (text), then Enter").lower()
        kind = {"q": "quantity", "t": "text"}.get(reply, "")
        if not kind:
            print(f"  '{reply}' is not q or t - type just the single letter q or t")
    answer = ask('Answer as the report writes it, WITH unit and scale (e.g. EUR 387.2 million)')
    page_str = ask("PDF page number")
    quote = ask("Quote: short text copied from that page that contains the answer")

    entry = {"id": next_id, "doc": doc, "question": question, "type": kind,
             "answer": answer, "page": int(page_str) if page_str.isdigit() else page_str,
             "quote": quote}
    if kind == "text":
        entry["aliases"] = [a.strip() for a in ask("Other accepted spellings, comma-separated").split(",") if a.strip()]
    entry["verified"] = ask("Have you seen this answer on that page in the PDF yourself? (y/n)").lower() == "y"
    entry["notes"] = ask("Notes (optional, Enter to skip)", allow_empty=True)

    errs = check_entry(entry, manifest, {})
    if errs:
        print(f"\nNOT SAVED - {next_id} has problems:")
        for e in errs:
            print("  ✗", e)
        print("Run add.py again with the corrected values.")
        return 1

    # json.dumps produces a correctly escaped double-quoted string, which is valid YAML
    lines = [f"\n- id: {next_id}"]
    for key in ("doc", "question", "type", "answer", "page", "quote", "aliases", "verified", "notes"):
        if key not in entry:
            continue
        v = entry[key]
        if isinstance(v, bool):
            v = "true" if v else "false"
        elif isinstance(v, (int, list)):
            v = json.dumps(v, ensure_ascii=False)
        else:
            v = json.dumps(v, ensure_ascii=False)
        lines.append(f"  {key}: {v}")
    with open(GT, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    status = "verified" if entry["verified"] else "PENDING - not used for grading until verified"
    print(f"\nSAVED {next_id} ({status}).")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled - nothing saved.")
        sys.exit(1)
