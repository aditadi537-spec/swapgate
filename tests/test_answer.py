import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from answer import build_prompt, combine, grade, parse_reply, BadFormat  # noqa: E402

# Small fake pages, so these tests don't depend on the (git-ignored) PDFs.
SHOWN = {
    234: "Consolidated income statement\nin m EUR 2025 2024\nRevenue (1.) 12,346.1 10,572.5\nNet result -698.2",
    85: "Revenue was up 16.8% to 12,346.1m EUR (prior year: 10,572.5m EUR)",
}
REV = {"type": "quantity", "answer": "EUR 12,346.1 million"}
SEG = {"type": "text", "answer": "Americas", "aliases": ["The Americas"]}


def J(raw='"12,346.1"', unit='"EUR million"', quote='"Revenue (1.) 12,346.1"', page="234"):
    return f'{{"raw_value": {raw}, "unit": {unit}, "source_quote": {quote}, "page": {page}}}'


@pytest.mark.parametrize("reply,verdict", [
    (J(), "pass"),
    ("```json\n" + J() + "\n```", "pass"),                          # fenced
    ("Sure! Here is the answer:\n" + J() + "\nHope that helps.", "pass"),  # prose around it
    (J(raw='"EUR 12,346.1 million"'), "pass"),                     # unit in both fields
    (J(raw='"12.3461"', unit='"EUR billion"'), "pass"),            # model rescaled; still same value
    (J(page="85", quote='"up 16.8% to 12,346.1m EUR"'), "pass"),   # other honest page
    (J(raw='"12,346.1"', unit='"EUR"'), "wrong_value"),            # dropped 'million'
    (J(raw='"10,572.5"'), "wrong_value"),                          # wrong year's column
    (J(unit='"USD million"'), "unit_mismatch"),
    (J(quote='"Revenue was a record 12,346.1"'), "bad_citation"),  # made-up quote
    (J(page="99"), "bad_citation"),                                # page never shown
    (J(raw="null", quote='""', page="null"), "no_answer"),
    ("The revenue was EUR 12,346.1 million.", "bad_format"),       # prose only
    ('{"value": "12,346.1"}', "bad_format"),                       # wrong field names
    ("", "bad_format"),
])
def test_verdicts(reply, verdict):
    assert grade(REV, reply, SHOWN)["verdict"] == verdict


def test_text_answer():
    shown = {25: "Americas $ 178,353 7 %"}
    ok = '{"raw_value": "Americas", "unit": "", "source_quote": "Americas $ 178,353", "page": 25}'
    wrong = '{"raw_value": "Europe", "unit": "", "source_quote": "Americas $ 178,353", "page": 25}'
    assert grade(SEG, ok, shown)["verdict"] == "pass"
    assert grade(SEG, wrong, shown)["verdict"] == "wrong_value"


def test_combine_does_not_double_scale():
    assert combine("EUR 12,346.1 million", "EUR million") == "EUR 12,346.1 million"
    assert combine("12,346.1", "EUR million") == "12,346.1 EUR million"


def test_prompt_contains_every_shown_page_once():
    msgs = build_prompt("What was revenue?", SHOWN)
    user = msgs[1]["content"]
    assert user.count("=== PAGE 234 ===") == 1 and user.count("=== PAGE 85 ===") == 1
    assert user.rstrip().endswith("Question: What was revenue?")


def test_non_numeric_page_is_bad_format():
    with pytest.raises(BadFormat):
        parse_reply('{"raw_value": "1", "unit": "", "source_quote": "", "page": "two hundred"}')


def test_dash_variants_in_quotes_count_as_the_same():
    # Found 2026-11-07 with a real model: DH p.85 prints "–" (en dash), p.166 prints "−" (minus).
    # A model retyping one as the other is not fabricating a quote.
    shown = {85: "Net result –698.2 –881.7 183.4 –20.8"}
    reply = '{"raw_value": "−698.2", "unit": "EUR million", "source_quote": "Net result −698.2 −881.7", "page": 85}'
    entry = {"type": "quantity", "answer": "EUR −698.2 million"}
    assert grade(entry, reply, shown)["verdict"] == "pass"
    # ...but a different NUMBER is still a fabricated quote
    bad = reply.replace("−881.7", "−818.7")
    assert grade(entry, bad, shown)["verdict"] == "bad_citation"
