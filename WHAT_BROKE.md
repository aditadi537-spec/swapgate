# What broke (raw material for the Loom)

Every entry: what happened, why nothing warned us, what we changed.

## 1. Precision rule could never be satisfied (2026-11-04)
- **What:** "answers need ≥3 significant figures". A dividend of EUR 0.82 only has 2,
  so no answer could ever meet the rule. Right answers passed only by exact match,
  and a wrong answer (EUR 0.28) was labelled "low precision" instead of "wrong".
- **Why silent:** the tests were green. The *reason* on the failure was wrong, not the colour.
- **Fix:** the precision floor can never be stricter than the true answer itself.

## 2. Asked for Python 3.12, got 3.15 (2026-11-05)
- **What:** `uv init --python 3.12` wrote `>=3.12`, so uv installed the newest (3.15).
- **Why silent:** every command succeeded. Only reading the last line showed it.
- **Fix:** `uv python pin 3.12`, an exact pin instead of a minimum.

## 3. Hyphens in words flipped numbers negative (2026-11-05)
- **What:** "non-current assets EUR 1,234 million" was parsed as **−1,234 million**.
  "year-on-year growth of 5.2%" became **−5.2%**.
- **Why silent:** 28/28 tests passed. No test contained a hyphenated word, yet annual
  reports are full of them. A correct model would have been marked wrong, so the
  gate would have blocked a good model because of a bug in *our* grader.
- **Fix:** a minus only counts directly before the number. Test written first, seen
  failing (red), then fixed (green). 33 tests.
