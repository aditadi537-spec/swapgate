"""The contract with every model: one prompt, one answer format, one verdict.

build_prompt()  - the exact instructions every model receives, plus the shown pages
parse_reply()   - pulls our JSON object out of a model's reply, or says why it can't
grade()         - turns (answer-key entry, reply, shown pages) into exactly one verdict

Verdicts, checked in this order (the first problem found wins):
  bad_format     reply is not valid JSON in our structure
  no_answer      the model said it could not find the answer (raw_value null)
  unparseable / unit_mismatch / low_precision / wrong_value   - from normalize.py
  loose_quote    value is right, the quote's numbers are on the cited page, but its wording
                 is not verbatim (e.g. a heading stitched into a table row)
  bad_citation   value is right, but the quote contains numbers that are NOT on the cited
                 page, or the cited page was never shown - invented evidence
  pass           right value, right unit, real quote on the cited page
"""
from __future__ import annotations

import json
import re

from normalize import Truth, Verdict, compare, compare_text

SYSTEM = """You extract one figure or fact from company annual report pages.

Rules:
- Use ONLY the pages provided. Do not use outside knowledge.
- raw_value: copy the number EXACTLY as printed on the page, with its sign, brackets,
  commas and decimals (e.g. "12,346.1", "-1,080.3", "(4)", "−698.2"). Do not convert,
  round or rescale it. For a non-numeric answer, give the name exactly as printed.
- unit: the currency, scale and/or % that applies to that number, often stated in the
  table header (e.g. "EUR million", "$ million", "%", "pp", "thousand"). Empty string if none.
- source_quote: a short span copied verbatim from the page that contains the value.
- page: the number from the "=== PAGE n ===" line of the page you took it from.
- If the answer is not on the provided pages, set raw_value to null.

Reply with ONLY this JSON object and nothing else:
{"raw_value": "...", "unit": "...", "source_quote": "...", "page": 0}"""


def build_prompt(question: str, pages: dict[int, str]) -> list[dict]:
    """pages: {page_number: text}. Same pages, same order, for every model."""
    body = "\n\n".join(f"=== PAGE {p} ===\n{t.strip()}" for p, t in pages.items())
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"{body}\n\nQuestion: {question}"},
    ]


class BadFormat(ValueError):
    pass


def parse_reply(text: str) -> dict:
    """Accepts the JSON object alone, inside ```json fences, or surrounded by prose.
    Anything else - or a JSON object with the wrong fields - is BadFormat."""
    if not text or not text.strip():
        raise BadFormat("empty reply")
    candidates = re.findall(r"\{.*?\}", text, re.S) or []
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        candidates.insert(0, fenced.group(1))
    for c in candidates:
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "raw_value" in obj:
            break
    else:
        raise BadFormat("no JSON object with a raw_value field found")
    missing = [k for k in ("raw_value", "unit", "source_quote", "page") if k not in obj]
    if missing:
        raise BadFormat(f"missing fields: {missing}")
    if obj["raw_value"] is not None and not isinstance(obj["raw_value"], (str, int, float)):
        raise BadFormat("raw_value must be text, a number or null")
    try:
        obj["page"] = int(obj["page"]) if obj["page"] is not None else None
    except (TypeError, ValueError):
        raise BadFormat(f"page is not a number: {obj['page']!r}")
    obj["raw_value"] = None if obj["raw_value"] is None else str(obj["raw_value"])
    obj["unit"] = "" if obj["unit"] is None else str(obj["unit"])
    obj["source_quote"] = "" if obj["source_quote"] is None else str(obj["source_quote"])
    return obj


def combine(raw_value: str, unit: str) -> str:
    """'12,346.1' + 'EUR million' -> '12,346.1 EUR million'. Unit words the model already
    put into raw_value are not added twice ('EUR 12,346.1 million' + 'EUR million')."""
    out = raw_value
    for word in unit.split():
        if word.lower() not in raw_value.lower():
            out += f" {word}"
    return out


_NUM = re.compile(r"\d[\d.,']*\d|\d")
DASHES = str.maketrans({"\u2212": "-", "\u2013": "-", "\u2014": "-", "\u2012": "-", "\u2010": "-"})


def _nospace(s: str) -> str:
    """For quote matching: ignore spacing, case, and WHICH dash character is used.
    The same report prints a minus as − on one page and – on another (DH p.166 vs p.85)."""
    return re.sub(r"\s+", "", s).lower().translate(DASHES)


def grade(entry: dict, reply_text: str, shown: dict[int, str], locale: str = "en") -> dict:
    """Returns {"verdict": ..., "detail": ..., "reply": parsed-or-None}."""
    try:
        r = parse_reply(reply_text)
    except BadFormat as ex:
        return {"verdict": "bad_format", "detail": str(ex), "reply": None}

    if r["raw_value"] is None or not r["raw_value"].strip():
        return {"verdict": "no_answer", "detail": "model said the answer is not on the pages", "reply": r}

    if entry["type"] == "text":
        res = compare_text(r["raw_value"], [entry["answer"], *entry.get("aliases", [])])
    else:
        res = compare(combine(r["raw_value"], r["unit"]), Truth(entry["answer"], locale), locale)
    if res.verdict != Verdict.PASS:
        return {"verdict": res.verdict.value, "detail": res.detail, "reply": r}

    page = r["page"]
    if page not in shown:
        return {"verdict": "bad_citation", "detail": f"cited page {page} was not among the pages shown {sorted(shown)}", "reply": r}
    quote = r["source_quote"]
    if not quote.strip():
        return {"verdict": "bad_citation", "detail": "no quote given", "reply": r}
    if _nospace(quote) not in _nospace(shown[page]):
        # Not verbatim. Are all its NUMBERS on the cited page (stitched/reworded quote),
        # or does it contain numbers that are not there (invented evidence)?
        q_nums = set(_NUM.findall(quote.translate(DASHES)))
        page_nums = set(_NUM.findall(shown[page].translate(DASHES)))
        if q_nums and q_nums <= page_nums:
            return {"verdict": "loose_quote",
                    "detail": f"numbers are on page {page}, but the wording is not verbatim", "reply": r}
        missing = sorted(q_nums - page_nums)
        why = f"numbers {missing} are not on page {page}" if missing else f"quote not found on page {page}"
        return {"verdict": "bad_citation", "detail": why, "reply": r}
    return {"verdict": "pass", "detail": "", "reply": r}
