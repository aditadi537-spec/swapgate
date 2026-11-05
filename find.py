"""Find which PDF page(s) contain some text.

Usage:   uv run python find.py <doc_id> <text to find>
Example: uv run python find.py zalando_2025 12,346.1

Use this while writing ground truth: find the number in the PDF yourself,
then run this to get the exact PDF page number and the line it sits on.
"""
import json
import re
import sys
from pathlib import Path


def squash(s: str) -> str:
    """Lower-case and collapse runs of spaces, so 'Revenue    12,346.1' matches 'revenue 12,346.1'."""
    return re.sub(r"\s+", " ", s).strip().lower()


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    doc_id, needle = sys.argv[1], " ".join(sys.argv[2:])
    path = Path(__file__).parent / "corpus_text" / f"{doc_id}.jsonl"
    if not path.exists():
        print(f"No extracted text for '{doc_id}'. Did you run extract.py? Known docs:",
              [p.stem for p in path.parent.glob("*.jsonl")])
        sys.exit(1)

    hits = []
    for line_json in path.read_text(encoding="utf-8").splitlines():
        page = json.loads(line_json)
        for line in page["text"].splitlines():
            if squash(needle) in squash(line):
                hits.append((page["page"], squash(line)))

    pages = sorted({p for p, _ in hits})
    print(f'"{needle}" appears on {len(pages)} page(s) of {doc_id}: {pages}\n')
    for page, line in hits[:25]:
        print(f"  page {page:>3} | {line[:130]}")
    if len(hits) > 25:
        print(f"  ... and {len(hits) - 25} more lines")


if __name__ == "__main__":
    main()
