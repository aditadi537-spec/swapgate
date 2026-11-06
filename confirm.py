"""Confirm drafted ground-truth entries one at a time, against the PDF.

Usage: uv run python confirm.py

For each entry with verified: false it shows the question, answer, page and quote.
Open the PDF at that page (Cmd + Option + G in Preview), look, then type:
  y  = I saw this exact answer on this page, and it answers this question
  n  = something is wrong (you will be asked what) - stays unverified
  s  = skip for now
  q  = quit (everything answered so far is saved)
"""
import datetime
import re
import sys
from pathlib import Path

import yaml

GT = Path(__file__).parent / "ground_truth.yaml"


def set_fields(text: str, eid: str, verified: bool, note: str) -> str:
    """Change verified/notes inside ONE entry's block, leaving the rest of the file as it is."""
    lines = text.split("\n")
    start = next(i for i, l in enumerate(lines) if l.strip() == f"- id: {eid}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("- id:")), len(lines))
    for i in range(start, end):
        if re.match(r"^  verified:", lines[i]):
            lines[i] = f"  verified: {'true' if verified else 'false'}"
        elif re.match(r"^  notes:", lines[i]):
            lines[i] = "  notes: " + yaml.safe_dump(note, default_style='"', allow_unicode=True).strip()
    return "\n".join(lines)


def main() -> int:
    entries = yaml.safe_load(GT.read_text(encoding="utf-8")) or []
    pending = [e for e in entries if not e.get("verified")]
    if not pending:
        print("Nothing to confirm - every entry is verified.")
        return 0
    today = datetime.date.today().isoformat()
    print(f"{len(pending)} entries to confirm. Open the PDF next to this window.\n")
    done = 0
    for n, e in enumerate(pending, 1):
        print("=" * 78)
        print(f"[{n}/{len(pending)}]  {e['id']}   {e['doc']}.pdf  ->  PAGE {e['page']}   (Cmd+Option+G)")
        print(f"  Question: {e['question']}")
        print(f"  Answer:   {e['answer']}")
        print(f"  Quote:    {e['quote']}")
        if e.get("aliases"):
            print(f"  Also OK:  {', '.join(e['aliases'])}")
        if e.get("notes"):
            print(f"  Notes:    {e['notes']}")
        while True:
            r = input("  Seen it on that page and it is correct? [y / n / s=skip / q=quit]: ").strip().lower()
            if r in ("y", "n", "s", "q"):
                break
            print("  type just one letter: y, n, s or q")
        if r == "q":
            break
        if r == "s":
            continue
        text = GT.read_text(encoding="utf-8")
        if r == "y":
            text = set_fields(text, e["id"], True, f"Confirmed by Adit in PDF p.{e['page']}, {today}.")
            done += 1
            print("  ✓ verified")
        else:
            why = input("  What is wrong? (short): ").strip()
            text = set_fields(text, e["id"], False, f"REJECTED by Adit {today}: {why}")
            print("  ✗ left unverified - tell Claude what was wrong")
        GT.write_text(text, encoding="utf-8")
    print(f"\n{done} confirmed this session. Now run: uv run python verify.py")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nStopped - everything answered so far is saved.")
        sys.exit(0)
