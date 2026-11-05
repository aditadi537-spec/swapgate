import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from normalize import Truth, Verdict, compare, compare_text, parse_quantity  # noqa: E402

REV = Truth("EUR 3,810.2 million")  # the canonical example from the brief


# --- The three phrasings from the brief must all agree -----------------------
@pytest.mark.parametrize("answer", [
    "3.81bn EUR", "EUR 3,810 million", "€3,810.2m", "3,810.2 EUR million",
    "EUR 3.81 billion", "€ 3 810,2 Mio.",
])
def test_equivalent_phrasings_pass(answer):
    locale = "de" if "Mio" in answer else None
    assert compare(answer, REV, answer_locale=locale).verdict == Verdict.PASS


# --- The cases fuzzy matching would wave through -----------------------------
@pytest.mark.parametrize("answer,verdict", [
    ("EUR 3,180 million", Verdict.WRONG_VALUE),     # digit transposition
    ("EUR 3.81 million", Verdict.WRONG_VALUE),      # scale error, 1000x off
    ("USD 3,810.2 million", Verdict.UNIT_MISMATCH), # wrong currency
    ("3,810.2 million", Verdict.UNIT_MISMATCH),     # currency dropped
    ("EUR 3,812 million", Verdict.WRONG_VALUE),     # precise but wrong
    ("about EUR 4bn", Verdict.LOW_PRECISION),       # vague, numerically 'close'
    ("EUR 3.8bn", Verdict.LOW_PRECISION),           # 2 sig figs
    ("EUR 3,810.2m (2024: 3,500m)", Verdict.UNPARSEABLE),  # two numbers
    ("", Verdict.UNPARSEABLE),
    ("not disclosed", Verdict.UNPARSEABLE),
])
def test_wrong_answers_fail_for_the_right_reason(answer, verdict):
    assert compare(answer, REV).verdict == verdict


# --- Separator ambiguity is resolved by document locale ----------------------
def test_ambiguous_comma_en_is_thousands():
    assert parse_quantity("3,810", "en").value == 3810

def test_ambiguous_comma_de_is_decimal():
    assert parse_quantity("3,810", "de").value == Decimal("3.810")

def test_ambiguous_dot_de_is_thousands():
    assert parse_quantity("3.810", "de").value == 3810

def test_both_separators_unambiguous_in_any_locale():
    assert parse_quantity("3.810,25", "en").value == Decimal("3810.25")
    assert parse_quantity("3,810.25", "de").value == Decimal("3810.25")

def test_repeated_separator_is_grouping():
    assert parse_quantity("1,234,567").value == 1234567


# --- Signs, percentages, per-share, counts ----------------------------------
def test_parentheses_negative():
    assert parse_quantity("EUR (123.4) million").value == Decimal("-123400000.0")

def test_unicode_minus():
    assert parse_quantity("−5.2%").value == Decimal("-5.2")

def test_percent_vs_percentage_points_are_different_units():
    t = Truth("1.4 percentage points")
    assert compare("1.4pp", t).verdict == Verdict.PASS
    assert compare("140 bps", t).verdict == Verdict.PASS
    assert compare("1.4%", t).verdict == Verdict.UNIT_MISMATCH

def test_dividend_per_share_cents():
    t = Truth("EUR 0.82")
    assert compare("82 cents EUR", t).verdict == Verdict.PASS
    assert compare("€0.82 per share", t).verdict == Verdict.PASS
    assert compare("€0.28 per share", t).verdict == Verdict.WRONG_VALUE

def test_headcount():
    t = Truth("16,021")
    assert compare("16,021 employees", t).verdict == Verdict.PASS
    assert compare("approximately 16,000 FTEs", t).verdict == Verdict.WRONG_VALUE
    assert compare("16k", t).verdict == Verdict.LOW_PRECISION

def test_exact_small_integer_not_blocked_by_sig_figs():
    assert compare("7", Truth("7")).verdict == Verdict.PASS


# --- Categorical answers -----------------------------------------------------
def test_text_aliases():
    aliases = ["Cloud", "Cloud segment"]
    assert compare_text("The Cloud segment.", aliases).verdict == Verdict.PASS
    assert compare_text("cloud", aliases).verdict == Verdict.PASS
    assert compare_text("Cloud & Software", aliases).verdict == Verdict.WRONG_VALUE


# --- Bug found 2026-11-05: hyphens inside words were read as minus signs ------
@pytest.mark.parametrize("answer,expected", [
    ("non-current assets EUR 1,234 million", Decimal("1234000000")),
    ("year-on-year growth of 5.2%", Decimal("5.2")),
    ("EUR -1,234 million", Decimal("-1234000000")),   # real minus must still work
    ("-5.2%", Decimal("-5.2")),
    ("€-3.2bn", Decimal("-3200000000")),
])
def test_hyphen_in_words_is_not_a_minus_sign(answer, expected):
    assert parse_quantity(answer).value == expected
