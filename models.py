"""Models the runner can ask. Every model has a name and ask(messages) -> reply text.

Fake models (free, instant, fully predictable) come first. They let us test the whole
pipeline before spending money:
  fake-old  answers every question correctly (it reads the answer key). If it does
            not score 100%, the PIPELINE has a bug, not the model.
  fake-new  same, but deliberately broken on a few questions in realistic ways - the
            "newer model" whose swap the gate must refuse.
Real models (OpenRouter) are added in step 3.
"""
from __future__ import annotations

import json
import re

import yaml
from pathlib import Path

ROOT = Path(__file__).parent
NUM_WITH_SIGN = re.compile(r"[-−(]?\d[\d.,']*\d?\)?")


def _truth_reply(entry: dict) -> dict:
    """What a perfect model would reply for this answer-key entry."""
    if entry["type"] == "text":
        return {"raw_value": entry["answer"], "unit": "", "source_quote": entry["quote"], "page": entry["page"]}
    m = NUM_WITH_SIGN.search(entry["answer"])
    raw = m.group()
    unit = (entry["answer"][: m.start()] + " " + entry["answer"][m.end():]).replace("$", "$ ").split()
    return {"raw_value": raw, "unit": " ".join(unit), "source_quote": entry["quote"], "page": entry["page"]}


class FakeModel:
    # question id -> how fake-new gets it wrong. "flaky" = wrong on the 2nd of every 3 asks.
    BREAKS = {
        "Q04": lambda r: {**r, "unit": "$ million"},                       # header scale applied to EPS
        "Q12": lambda r: {**r, "unit": "%"},                               # % instead of pp
        "Q15": lambda r: {**r, "raw_value": r["raw_value"].lstrip("−-")},  # minus sign dropped
        "Q22": lambda r: {**r, "source_quote": "Adjusted EBITDA reached a record 903.0"},  # made-up quote
    }
    FLAKY = {"Q20"}

    def __init__(self, name: str):
        self.name = name
        gt = yaml.safe_load((ROOT / "ground_truth.yaml").read_text(encoding="utf-8"))
        self.by_question = {e["question"]: e for e in gt}
        self.calls = {}

    def ask(self, messages: list[dict]) -> str:
        content = messages[-1]["content"]
        question = content.rsplit("Question: ", 1)[-1].strip()
        entry = self.by_question[question]
        reply = _truth_reply(entry)
        # Like a real model, it can only cite pages it was SHOWN. If the official page is
        # not among them, cite the first shown page that contains the value, quoting its line.
        shown = {int(n): t for n, t in re.findall(r"=== PAGE (\d+) ===\n(.*?)(?=\n\n=== PAGE |\n\nQuestion: )", content, re.S)}
        if entry["page"] not in shown:
            needle = reply["raw_value"]
            for page, text in shown.items():
                line = next((l for l in text.splitlines() if needle in l), None)
                if line:
                    reply = {**reply, "page": page, "source_quote": " ".join(line.split())}
                    break
        n = self.calls[entry["id"]] = self.calls.get(entry["id"], 0) + 1
        if self.name == "fake-new":
            if entry["id"] in self.BREAKS:
                reply = self.BREAKS[entry["id"]](reply)
            if entry["id"] in self.FLAKY and n % 3 == 2:
                reply = {**reply, "raw_value": "903.0"}   # occasionally grabs a neighbouring figure
        return json.dumps(reply, ensure_ascii=False)


def get_model(name: str):
    if name in ("fake-old", "fake-new"):
        return FakeModel(name)
    raise ValueError(f"unknown model {name!r} (real models arrive in step 3)")
