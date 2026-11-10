"""Step 6: turn each PDF in corpus/ into text, one record per page.

Writes:
  corpus_text/<doc_id>.jsonl   one line per page: {"page": 12, "text": "..."}
  corpus/manifest.json         which files we used, with a fingerprint of each

Page numbers are PDF page numbers (1 = first page of the file), NOT the numbers
printed on the pages. Printed numbers usually start later (cover, contents),
and mixing the two would make every page citation off by a few.
"""
import hashlib
import json
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).parent

# doc_id: (file name in corpus/, how numbers are written in this document)
DOCS = {
    "zalando_2025": ("zalando_2025.pdf", "en"),
    "deliveryhero_2025": ("deliveryhero_2025.pdf", "en"),
    "apple_10k_2025": ("apple_10k_2025.pdf", "en"),
}


def fingerprint(path: Path) -> str:
    """SHA-256: a 64-character code unique to this exact file. Change one byte
    of the PDF and the code changes completely, so it proves which file we used."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    out_dir = ROOT / "corpus_text"
    out_dir.mkdir(exist_ok=True)
    manifest_path = ROOT / "corpus" / "manifest.json"
    # The committed fingerprints are the proof of WHICH files the answer key was verified
    # against. They are compared, never silently replaced.
    committed = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest, problems = {}, []

    for doc_id, (fname, locale) in DOCS.items():
        path = ROOT / "corpus" / fname
        if not path.exists():
            problems.append(f"{doc_id}: file not found at {path}")
            continue

        sha = fingerprint(path)
        expected = committed.get(doc_id, {}).get("sha256")
        if expected and sha != expected:
            problems.append(f"{doc_id}: {fname} is a DIFFERENT file than the answer key was verified against "
                            f"(sha256 {sha[:12]}..., expected {expected[:12]}...). Download the exact version.")
            continue

        doc = pymupdf.open(path)
        near_empty, written = [], 0
        out_file = out_dir / f"{doc_id}.jsonl"
        with open(out_file, "w", encoding="utf-8") as f:
            for page_no, page in enumerate(doc, start=1):
                text = page.get_text("text", sort=True)  # sort=True: reading order
                if len(text.split()) < 20:  # covers, photos, section dividers
                    near_empty.append(page_no)
                f.write(json.dumps({"page": page_no, "text": text}, ensure_ascii=False) + "\n")
                written += 1

        # Reconcile: re-read what we wrote and check it matches the PDF.
        lines = out_file.read_text(encoding="utf-8").splitlines()
        if written != doc.page_count or len(lines) != doc.page_count:
            problems.append(f"{doc_id}: PDF has {doc.page_count} pages but we wrote {len(lines)}")

        manifest[doc_id] = {
            "file": fname,
            "sha256": sha,
            "pages": doc.page_count,
            "locale": locale,
            "near_empty_pages": near_empty,
        }
        print(f"{doc_id:20} {doc.page_count:4} pages   {len(near_empty):3} near-empty   -> {out_file.name}")

    if problems:
        print("\nREFUSED - extraction does not reconcile:")
        for p in problems:
            print("  -", p)
        print("(corpus/manifest.json was NOT changed.)")
        return 1
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print("\nOK - every page extracted and reconciled. Manifest: corpus/manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
