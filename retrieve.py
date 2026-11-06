"""Pick the pages each model gets to read for a question (retrieval).

Every model receives EXACTLY the same pages for a given question, so a difference
in answers is the model's doing, not the retrieval's. We also record whether the
page holding the right answer was among them: if it wasn't, a wrong answer is a
retrieval failure, not a model failure.

Method: BM25, a classic keyword-ranking formula. A page scores higher when it
contains the question's words often, and rare words count far more than common
ones ("investing" beats "Zalando", which is on every page).

Usage (shows how well retrieval finds the right page for all 30 questions):
    uv run python retrieve.py
"""
import json
import math
import re
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
TOP_K = 5
STOPWORDS = set("""a an and are as at be by did do does for from had has have how in is it its
of on or than that the their this to was were what which with according during
compared""".split())


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+|\d[\d,.]*\d|\d", text.lower()) if w not in STOPWORDS]


class Index:
    def __init__(self, doc_id: str, k1: float = 1.5, b: float = 0.75):
        rows = [json.loads(l) for l in (ROOT / "corpus_text" / f"{doc_id}.jsonl").read_text(encoding="utf-8").splitlines()]
        self.text = {r["page"]: r["text"] for r in rows}
        self.tf = {p: Counter(tokens(t)) for p, t in self.text.items()}
        self.len = {p: sum(c.values()) for p, c in self.tf.items()}
        self.avg_len = sum(self.len.values()) / len(self.len)
        df = Counter(w for c in self.tf.values() for w in c)
        n = len(self.tf)
        self.idf = {w: math.log(1 + (n - d + 0.5) / (d + 0.5)) for w, d in df.items()}
        self.k1, self.b = k1, b

    def score(self, page: int, query: list[str]) -> float:
        tf, s = self.tf[page], 0.0
        for w in query:
            if w in tf:
                f = tf[w]
                s += self.idf[w] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[page] / self.avg_len))
        return s

    def top(self, question: str, k: int = TOP_K) -> list[int]:
        q = tokens(question)
        return sorted(self.tf, key=lambda p: self.score(p, q), reverse=True)[:k]


def main() -> None:
    entries = [e for e in yaml.safe_load((ROOT / "ground_truth.yaml").read_text(encoding="utf-8")) if e["verified"]]
    indexes = {}
    hits = 0
    for e in entries:
        idx = indexes.setdefault(e["doc"], Index(e["doc"]))
        pages = idx.top(e["question"])
        found = e["page"] in pages
        hits += found
        print(f"{e['id']}  {'✓' if found else '✗'}  right page {e['page']:>3}  shown {pages}")
    print(f"\nRight page among the {TOP_K} shown: {hits}/{len(entries)} questions")


if __name__ == "__main__":
    main()
