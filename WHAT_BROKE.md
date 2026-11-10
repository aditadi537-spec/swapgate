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

## 7. The "always correct" fake model scored 27/30 (2026-11-06)
- **What:** fake-old reads the answer key, so it must score 100%. It scored 27/30: for the 3
  questions where retrieval did not show the official page, it cited that unseen page anyway,
  and the citation check (correctly) failed it.
- **Why it matters:** the check worked. A real model answering from memory instead of from the
  pages would do exactly this - cite something it was never shown - and now we know it gets caught.
- **Fix:** the fake model, like a real one, may only cite pages it was shown. Then fake-old = 30/30,
  and fake-new failed on exactly the 5 planted problems: no more, no less.
- **Lesson:** a known-perfect input is the cheapest way to test a pipeline. If it doesn't score
  100%, the bug is yours.

## 8. Two different minus signs in one report (2026-11-07, first real model)
- **What:** qwen3:8b answered Delivery Hero's net result correctly (−698.2) and cited p.85.
  The citation check said "quote not on page". Page 85 prints the minus as "–" (en dash,
  U+2013); page 166 prints it as "−" (minus sign, U+2212). The quote used the p.166 character.
- **Why silent:** the characters look identical. Every model would have been marked down on
  Delivery Hero for a fabricated citation, and we would have blamed the models.
- **Fix:** citation and answer-key checks treat all dash characters as the same; a different
  NUMBER in a quote still fails. Test written from the real reply, seen red, then green.

## 9. The cloud model was too busy to take the exam (2026-11-07)
- **What:** Gemini 3.7 Flash on the free tier: one timeout after 120s, then "HTTP 503 - this model
  is currently experiencing high demand". Gemini 3.8 Flash passed on the same question minutes later.
- **Why it matters:** a server failure is not a wrong answer. A gate that counted it as one would
  block a good model because Google was busy on a Saturday evening.
- **Fix:** timeouts on every call, 429/503 retried a few times with a visible message, and failed
  calls recorded as verdict "error", which the gate must never count as a regression.
- **Decision:** the live demo runs on local models (qwen3 -> qwen3.5): free, unlimited, offline,
  so it cannot be "too busy" while recording. Gemini 3.7 -> 3.8 is the second, cloud pair.

## 10. Two page numbers on every page (2026-11-07, qwen3:8b)
- **What:** Apple Q26: right answer, but cited "page 4". Our label said "=== PAGE 7 ===", and the
  page's own footer says "Apple Inc. | 2025 Form 10-K | 4". The model used the printed number.
- **Why it matters:** the input itself contains a competing page number. Real customer documents
  have footers too - a citation check is only as good as how unambiguous the page labels are.
- **Decision:** NOT fixed mid-experiment. Changing the prompt between the old and new model's runs
  would change the workflow being tested - and tuning the setup until results look good is
  exactly the habit this project warns against. Both models get the same input.
- **Later improvement:** strip printed footers, or label pages so they can't be confused.

## 11. A grading rule changed after a run had started (2026-11-07)
- **What:** loose_quote was added while qwen3:8b was mid-run, so its replies were judged by old rules.
- **Fix:** every raw reply is stored, so regrade.py re-judges all runs with the current rules in
  seconds, without asking any model again. Comparing runs judged by different rules is as
  invalid as comparing runs with different answer keys.

## 12. A refused extraction erased the proof (2026-11-10, fresh-clone test)
- **What:** testing the repo the way a stranger would (fresh clone, follow the README) showed
  that extract.py, when it REFUSED because the PDFs were missing, still overwrote
  corpus/manifest.json with an empty file - erasing the fingerprints of the exact PDFs the
  answer key was verified against. And with PDFs present, it never compared them to those
  fingerprints: a different version of a report would have been accepted silently.
- **Why silent:** every piece had been tested on its own, on a machine that already had the PDFs.
- **Fix:** fingerprints are compared, never silently replaced; nothing is written on refusal.
  Tested: no PDFs -> refused, manifest untouched; right PDFs -> identical fingerprints;
  Apple's 10-K renamed to zalando_2025.pdf -> "DIFFERENT file than the answer key was verified against".
- **Lesson:** test the way the next person will use it, not the way you built it.
