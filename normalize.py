"""Normalisation + comparison layer.

Turns answers like "3.81bn", "EUR 3,810 million", "(12.4)%", "3.810,2 Mio. €"
into a typed Quantity, then compares it to hand-verified ground truth.

Design decisions (each one is deliberate - see README):
  1. WE parse the model's verbatim string. The model never does the unit
     conversion we are grading (bn -> million errors hide exactly there).
  2. Ambiguous separators ("3,810" / "3.810") are resolved by the DOCUMENT's
     number locale, never guessed per answer.
  3. Tolerance is precision-aware: an answer is right if the truth rounds to
     what the answer claimed. "3.81bn" passes for 3,810.2m; "3,812m" fails.
  4. A minimum number of significant figures stops "about 4bn" from passing.
  5. Units are strict: a dropped or wrong currency is a failure, because a
     downstream workflow consuming the value breaks on it.
  6. More than one number in an answer = unparseable. Ambiguity is a failure,
     not something we resolve in the model's favour.
  7. No fuzzy matching anywhere. "3,180" vs "3,810" is 90% string-similar
     and completely wrong.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class Verdict(str, Enum):
    PASS = "pass"
    WRONG_VALUE = "wrong_value"
    UNIT_MISMATCH = "unit_mismatch"
    LOW_PRECISION = "low_precision"
    UNPARSEABLE = "unparseable"


class Unparseable(ValueError):
    pass


@dataclass(frozen=True)
class Quantity:
    value: Decimal       # in base units: EUR, not EUR million
    unit: str | None     # ISO currency, "%", "pp", or None for plain counts
    step: Decimal        # smallest increment the string expressed, base units
    sig_figs: int


@dataclass(frozen=True)
class Result:
    verdict: Verdict
    detail: str = ""


CURRENCY = {
    "€": "EUR", "eur": "EUR", "euro": "EUR", "euros": "EUR",
    "$": "USD", "usd": "USD", "dollar": "USD", "dollars": "USD",
    "£": "GBP", "gbp": "GBP", "chf": "CHF", "¥": "JPY", "jpy": "JPY",
}
SCALE = {
    "thousand": Decimal("1e3"), "thousands": Decimal("1e3"), "k": Decimal("1e3"),
    "tsd": Decimal("1e3"),
    "million": Decimal("1e6"), "millions": Decimal("1e6"), "mn": Decimal("1e6"),
    "m": Decimal("1e6"), "mio": Decimal("1e6"), "mm": Decimal("1e6"),
    "billion": Decimal("1e9"), "billions": Decimal("1e9"), "bn": Decimal("1e9"),
    "b": Decimal("1e9"), "bln": Decimal("1e9"), "mrd": Decimal("1e9"),
    "milliarden": Decimal("1e9"),
    "trillion": Decimal("1e12"), "tn": Decimal("1e12"),
    "cent": Decimal("0.01"), "cents": Decimal("0.01"), "ct": Decimal("0.01"),
}
PHRASES = [  # applied before tokenising, longest first
    ("percentage points", " pp "), ("percentage point", " pp "),
    ("basis points", " bps "), ("per cent", " % "), ("percent", " % "),
    ("us$", " usd "), ("'000", " thousand "), ("ppt", " pp "),
]

_SPACE_GROUP = re.compile(r"(?<=\d)[    ](?=\d{3}(?!\d))")
_NUM = re.compile(r"\d[\d.,']*\d|\d")
_WORD = re.compile(r"[a-z]+|[€$£¥%]")


def _parse_number(tok: str, locale: str) -> tuple[Decimal, int]:
    """Return (value, decimal_places) for a bare numeric token."""
    tok = tok.replace("'", "")  # Swiss thousands separator
    dots, commas = tok.count("."), tok.count(",")
    if dots and commas:  # both present: whichever comes last is the decimal mark
        dec = "." if tok.rfind(".") > tok.rfind(",") else ","
    elif dots + commas == 0:
        dec = None
    else:
        sep = "." if dots else ","
        after = tok.split(sep)[-1]
        if dots + commas > 1:
            dec = None  # 1,234,567 - repeated separator is always grouping
        elif len(after) == 3:  # "3,810" / "3.810": genuinely ambiguous
            en_dec = "."
            dec = sep if (sep == en_dec) == (locale == "en") else None
        else:
            dec = sep  # "3.81", "3,81"
    if dec is None:
        return Decimal(tok.replace(".", "").replace(",", "")), 0
    grp = "," if dec == "." else "."
    intpart, frac = tok.replace(grp, "").split(dec)
    return Decimal(f"{intpart}.{frac}"), len(frac)


def parse_quantity(raw: str, locale: str = "en") -> Quantity:
    if raw is None or not str(raw).strip():
        raise Unparseable("empty answer")
    s = _SPACE_GROUP.sub("", str(raw))           # "3 810,2" -> "3810,2"
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.replace("−", "-").replace("–", "-").replace("—", "-")

    nums = list(_NUM.finditer(s))
    if len(nums) != 1:
        raise Unparseable(f"expected exactly one number, found {len(nums)}")
    m = nums[0]
    number, places = _parse_number(m.group(), locale)

    prefix, suffix = s[: m.start()], s[m.end():]
    # A minus counts only if it sits right before the number (optionally with a
    # currency between). Hyphens inside words like "non-current" must not count.
    negative = bool(re.search(r"-\s*(?:[€$£¥]|eur|usd|gbp|chf|jpy)?\s*$", prefix)) or (
        "(" in prefix and ")" in suffix
    )

    rest = f"{prefix} {suffix}"
    for phrase, repl in PHRASES:
        rest = rest.replace(phrase, repl)

    currency = unit_other = None
    scale = Decimal(1)
    scales_seen = 0
    for w in _WORD.findall(rest):
        if w in CURRENCY:
            if currency and currency != CURRENCY[w]:
                raise Unparseable(f"conflicting currencies {currency}/{CURRENCY[w]}")
            currency = CURRENCY[w]
        elif w in SCALE:
            scales_seen += 1
            scale *= SCALE[w]
        elif w == "%":
            unit_other = "%"
        elif w == "pp":
            unit_other = "pp"
        elif w == "bps":
            unit_other, scale = "pp", scale * Decimal("0.01")
        # anything else ("employees", "per", "share") is a descriptive noun
    if scales_seen > 1:
        raise Unparseable("more than one scale word")
    if currency and unit_other:
        raise Unparseable(f"both a currency and {unit_other}")

    digits = re.sub(r"\D", "", m.group()).lstrip("0")
    value = -number * scale if negative else number * scale
    return Quantity(
        value=value,
        unit=currency or unit_other,
        step=Decimal(1).scaleb(-places) * scale,
        sig_figs=max(len(digits), 1),
    )


@dataclass(frozen=True)
class Truth:
    raw: str                 # written exactly as in the PDF
    locale: str = "en"
    min_sig_figs: int = 3

    @property
    def quantity(self) -> Quantity:
        return parse_quantity(self.raw, self.locale)


def compare(answer_raw: str, truth: Truth, answer_locale: str | None = None) -> Result:
    t = truth.quantity
    try:
        a = parse_quantity(answer_raw, answer_locale or truth.locale)
    except Unparseable as e:
        return Result(Verdict.UNPARSEABLE, str(e))

    if a.unit != t.unit:
        return Result(Verdict.UNIT_MISMATCH, f"got {a.unit}, expected {t.unit}")
    # The floor can never be stricter than the truth itself: EUR 0.82 has 2 sig figs.
    required = min(truth.min_sig_figs, t.sig_figs)
    if a.sig_figs < required:
        return Result(Verdict.LOW_PRECISION, f"{a.sig_figs} sig figs < {required}")
    tolerance = max(a.step, t.step) / 2
    diff = abs(a.value - t.value)
    if diff <= tolerance:
        return Result(Verdict.PASS)
    return Result(Verdict.WRONG_VALUE, f"off by {diff:,} (tolerance {tolerance:,})")


def _norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).casefold()
    s = re.sub(r"[^\w\s&]", " ", s)
    s = re.sub(r"^\s*the\s+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def compare_text(answer: str, aliases: list[str]) -> Result:
    """Categorical answers (e.g. 'fastest-growing segment'): exact match against
    hand-written aliases after light normalisation. No similarity scores."""
    if not answer or not answer.strip():
        return Result(Verdict.UNPARSEABLE, "empty answer")
    if _norm_text(answer) in {_norm_text(x) for x in aliases}:
        return Result(Verdict.PASS)
    return Result(Verdict.WRONG_VALUE, f"{answer!r} not in aliases")
