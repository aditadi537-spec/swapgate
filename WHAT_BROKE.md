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

## 4. The answer-key checker said OK to a duplicate (2026-11-06)
- **What:** while adding Q05, Terminal's up-arrow recalled Q04's answers. Q05 was saved
  as an exact copy of Q04. Every check passed, because the quote really was on page 32.
- **Why silent:** each entry was checked on its own; nothing compared entries with each other.
  A duplicated fact would have counted twice in the grid and skewed every model's score.
- **Caught by:** a human reading the saved output, not by the tool.
- **Fix:** verify.py and add.py now refuse a repeated question, or the same answer on the
  same page. Lesson: check each record, then check the records against each other.

## 5. Hand-typed YAML broke on indentation twice (2026-11-06)
- **What:** editing Q01 in TextEdit produced 4 spaces, then 3 spaces, then a line break inside a quote.
- **Fix:** add.py asks each field and writes the YAML itself. Humans supply facts, the tool supplies format.

## 6. Confirming is weaker than reading (2026-11-06)
- **What:** confirm.py shows the drafted answer next to the page number. Saying "y" to a number
  you are shown is easier than reading it yourself, because the eye tends to agree. Three
  entries were confirmed in a rushed moment and had to be reset and re-checked.
- **Fix:** reset the doubtful ones, then a BLIND spot-check: for 3 of the hardest entries, Adit got
  only the question and page and read the value himself. 3/3 matched the answer key.
- **Side finding:** copying DH p.166 from Preview gives the two columns in order, while PyMuPDF
  interleaves them line by line. Same PDF, different text depending on the reader, and the
  models will get the messy version.
