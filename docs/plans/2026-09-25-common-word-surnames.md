# Common-word names: "Will", "Young", "Grace" matching every use of the word

**Status: PROPOSED — awaiting a decision.** Nothing in this plan has been built.
**Written:** 25 September 2026
**Trigger:** the one detection finding from the 24 September audit that was left open on purpose. A student called Will Young has every "will" and "young" in the report offered for removal, ticked by default.

---

## 1. The problem, precisely

Names are matched case-insensitively. That is right for almost every name: "smith" in a report is the surname Smith, whatever the case. It is wrong for the names that are also ordinary English words:

| Name | Innocent uses in a school report |
|---|---|
| Will | "He will need support", "Will he attend?" |
| Young | "young people", "the younger students" (whole-word, so this one is safe), "at a young age" |
| Grace, Hope, Joy, Faith | "a period of grace", "we hope", "joy in reading" |
| Long, Short, Small, Little, Strong | "long division", "in the short term", "small group" |
| Brown, White, Green, Black, Grey | colours, in art and science reports |
| Rose, May, June, Summer, Autumn | "rose to the challenge", "in May", "over summer" |
| Bishop, Church, King, Knight, Hill, Wood, Stone, Field, Bell, Page, Park, Price, Reed, Cook, Baker, Mason | nouns and jobs |
| Best, Bright, Fair, Good, Kind, Sharp, Smart, Swift, Wise, Wild, Free | adjectives in every teacher comment |

Two things make this worse than "a few extra ticks to clear":

1. **Unticking does not work the way it looks.** Rule 11a in `CLAUDE.md`: once a string is selected, it is redacted on **every** page, wherever it appears. The redactor searches by string, not by the review row. So if the teacher ticks "Young" beside the student's surname and unticks the forty rows for "young" as a word, the forty are blacked out anyway. The review screen is not a mitigation for this class of name. It only looks like one.

2. **It is not only surnames.** The nickname map turns "William" into "Will" and "Bill", "Patricia" into "Pat", "Arthur" into "Art", "Raymond" into "Ray", "Susan" into "Sue", "Edward" into "Ted". A student called William Young is a worst case: "will" and "young" both flagged, plus "bill" (as in "the bill"), on every page.

The audit note recorded why this was left: the verifiers are case-insensitive by design, so a case-sensitive detector would self-quarantine. That reasoning was correct as far as it went. This plan is about doing it without the self-quarantine.

## 2. What already exists, and why that matters

Since the two-letter-name fix (rule 7), the pipeline **already has** a per-string case rule, and it is already applied consistently end to end:

| Place | Function | Today's rule |
|---|---|---|
| `src/core/pii_detector.py` | `match_flags(text)` | case-sensitive when `len(text) <= 2` |
| `src/core/redactor.py` | `_is_case_sensitive_pii(text)` | the same, mirrored |
| Detection (user names, NER variations, orgs) | `match_flags` | |
| Text-layer redaction | `_is_whole_word_match` → `_is_case_sensitive_pii` | |
| OCR redaction (scans and pictures) | `_match_and_redact_ocr_words` → `_is_case_sensitive_pii` | |
| Both redaction verifiers | `_pii_visible_in_text` → `_is_case_sensitive_pii` | |
| De-identify replace and verify | `text_deidentifier._pattern_for` → `_is_case_sensitive_pii` | |
| Manual "add a missed item" | rule 7 says it agrees; confirm in step 1 | |

So "Do" the surname is never confused with "do" the verb, and the file does not quarantine itself, because every stage asks the same question. **The whole plan is: widen that question from "is it two letters?" to "is it two letters, or a single word that is also an ordinary English word?"** The consistency is already built. The trade-off rule 7 accepted for "Do" and "He" (a sentence-initial "Do not…" is offered as a match; the teacher can untick it) is the same trade-off, applied to more names.

## 3. Options considered

**A. Widen the case rule (recommended).** A single-token name that is an ordinary English word matches only when it is not written entirely in lowercase. "Young", "YOUNG" and "Young's" match; "young" does not. Full names ("Will Young") are untouched, because two tokens together are not an ordinary word. Everything downstream follows automatically through the shared predicate.

**B. Change the review defaults instead** (leave common-word rows unticked, or lower their confidence). Rejected: because of rule 11a, an unticked "young" is still blacked out if any "Young" row is ticked. The defaults would describe a choice the redactor does not honour.

**C. Context heuristics** (only flag "Will" when followed by a surname, or preceded by a title, or not at the start of a sentence). Not now. It is a per-occurrence rule, and redaction is per-string, so it has the same rule 11a problem as B unless the redactor is also made per-occurrence, which is a much larger change. Could come later on top of A to trim the sentence-initial collateral.

**D. Leave it.** The status quo. The audit note already documents it. Rejected only because item 1 above means the mitigation we were relying on is not real.

## 4. The design, in detail

### 4a. One predicate, one home

Replace the two mirrored functions with one, in a new leaf module so neither `pii_detector` nor `redactor` has to import the other:

```
src/core/case_rules.py
    case_mode(text) -> 'exact' | 'not_lowercase' | 'ignore'
```

- `'exact'` — two characters or fewer. Today's rule, unchanged.
- `'not_lowercase'` — a single token (no spaces, no hyphens, no apostrophes) of three or more letters whose lowercase form is in the common-word list.
- `'ignore'` — everything else. Today's default, unchanged.

`match_flags` and `_is_case_sensitive_pii` become thin wrappers so no caller changes shape. The whole-word and OCR matchers gain one extra branch: for `'not_lowercase'`, compare lowercased **and then** reject the hit if the document's word is entirely lowercase (`word.islower()`). That is a smaller change than building a regex per mode, and it keeps "YOUNG" in a heading matching.

### 4b. The word list

Two candidate sources. **Decision needed — see section 6.**

- **A shipped frequency list.** The most common 5,000 to 10,000 English words, lowercase, one per line, about 80 KB, in `src/core/data/common_words.txt`. Catches names we would never think to curate. Risk: it also contains rare-word surnames ("Smith" is a word, as in blacksmith; "Baker", "Cook", "Turner", "Walker", "Carter" are all jobs). For those the effect is only that a **lowercase** "baker" in the text is left alone, which is what we want anyway. There is no case where a real name in prose is written all-lowercase, except inside email addresses and usernames, and those are matched as their own structured PII.
- **A curated list** of a few hundred name-words, hand-picked. Smaller, reviewable, no surprises. Misses whatever nobody thought of.

Recommendation: the frequency list, with a short curated file of additions and a test that prints any entered name that lands on the list, so a surprise is visible in the test output rather than in a teacher's document.

### 4c. Where case-insensitivity must STAY

- **Filenames.** `strip_pii_from_filename` stays case-insensitive. File names are very often all lowercase ("will young report.pdf") and contain no prose, so there is nothing to protect on that side. Rule 18 territory; add a line there.
- **Custom role sanitising** in de-identify mode (`PseudonymMap.sanitise_custom_role`) already lowercases both sides on purpose (rule 7's stated exception). Unchanged.
- **Multi-token strings** of any kind. "Will Young", "W. Young", "Young, Will", "van der Berg": unchanged.
- **Structured PII** (phones, emails, Medicare, addresses). Unchanged; they never go through the name predicate.

### 4d. Scanned pages

OCR reads "Young" as "Young" on a clean scan; the case is rarely what it gets wrong. On a poor scan it might read "young", and with this change that word would be left alone by the OCR redactor and, consistently, not reported by the OCR verifier. That is a real, small leak: a lowercase-misread common-word surname survives on a scan and the run reports success.

Two ways to handle it. **Decision needed — see section 6.**

- Accept it, and say so in the OCR-page warning that already appears on the completion screen ("scanned pages, manual review recommended"). Simplest and consistent.
- Keep scanned pages case-insensitive for common-word names (the extra branch in section 4a is skipped when the page is OCR-sourced), on the grounds that a scan has no reliable case to protect and over-redaction there is the existing behaviour. Then the OCR verifier must skip the case check on OCR pages too, or the file self-quarantines, which is the trap rule 7 warns about. Doable, but it puts a page-type condition into a predicate that today knows nothing about pages.

The fuzzy OCR matcher (rule 32) compares lowercase forms and tolerates one wrong letter for words of five letters or more. "young" is five letters, so the fuzzy branch would match it back to "Young" even after the exact branch declined it. Whichever option is chosen, the fuzzy branch must apply the same case check, or option one silently becomes option two for five-letter names only.

### 4e. The review screen

For a common-word name, show a small badge on each row: "common word — matched only when capitalised". One line in `DocumentReview.tsx`, driven by a flag the backend puts on the match. Not essential, but without it a teacher who searches the report for "young" and sees it untouched will think the tool missed it.

### 4f. What still gets flagged, and is accepted

Sentence-initial uses: "Will he attend?", "Young people often…", "Hope is not a strategy". These are capitalised, so they match, and the teacher unticks them exactly as they do for "Do not…" today. Each is a black box over a word, which is the safe direction. Option C above could trim these later.

## 5. Steps, each with its check

1. **Confirm the predicate really is shared.** Grep every case-handling site listed in section 2, including `/api/pii/manual` and the paste pathway. → *Check:* a list of call sites, each shown to reach `match_flags` or `_is_case_sensitive_pii`. Any that re-implements the length test gets pointed at the shared function first, as its own commit, before anything changes behaviour.

2. **Build the measurement corpus** (scratch, not committed): ten synthetic reports for "William Young" with parent "Grace Long", using will / young / grace / long / bill as ordinary words, a sentence-initial "Will", a heading in capitals, one scanned page, one pasted screenshot. → *Check:* a table of match counts per category per document, today. This is the "before" figure.

3. **Add `case_rules.py` and the word list**, with `match_flags` and `_is_case_sensitive_pii` delegating to it. No behaviour change yet if the list is empty. → *Check:* full suite green with an empty list.

4. **Populate the list and run the corpus.** → *Check:* the "after" table. Expect the ordinary-word rows to vanish and the name rows to remain; expect the sentence-initial rows to remain.

5. **Wire the `'not_lowercase'` branch** into `_is_whole_word_match`, `_match_and_redact_ocr_words` (including the fuzzy branch), `_pii_visible_in_text` and `_pattern_for`. → *Check:* on the corpus, both pathways redact / de-identify every capitalised occurrence, leave every lowercase one, and **no document quarantines**. This is the check that rule 7 says protects the whole design; it must be a committed test, not a scratch run.

6. **Filenames stay case-insensitive.** → *Check:* `test_filename_redaction.py` gains "will young report" → "[REDACTED] report".

7. **Decide and implement the scanned-page option** from section 4d. → *Check:* one test per option on a scanned corpus page with a lowercase misread.

8. **The review badge.** → *Check:* build and lint at baseline; the flag is present in the API response and asserted in a backend test.

9. **Documentation.** A rule in `CLAUDE.md` beside rule 7, the README's "Name Detection — In Depth" section, and a line in the release notes that a teacher would understand: "Names that are also ordinary words, like Will or Young, are now only removed when they are written as a name."

## 6. Decisions for Dave

1. **Word list source:** shipped frequency list plus curated additions (recommended), or curated only?
2. **Scanned pages:** accept the small lowercase-misread leak with a warning (recommended, simpler and consistent), or keep scans case-insensitive with the matching verifier change?
3. **The review badge:** worth the small frontend change, or leave the behaviour explained in the README only?
4. **Sentence-initial collateral:** accept it now, as rule 7 did for "Do" and "He", and consider option C later?

## 7. Risks, and what would stop the work

- **A real name written in lowercase in prose.** Not seen in any sample document; emails and usernames are covered separately. If step 2 turns one up, the design needs the context heuristics of option C, and the work should pause for a rethink.
- **A common-word name that is also in the nickname map** ("Will", "Bill", "Pat", "Sue", "Ray", "Ted", "Art"). The nickname is a generated variation and goes through the same predicate, so it is covered; step 4 should show it.
- **The word list catching a surname whose word sense is rare.** Effect is under-matching of an all-lowercase occurrence only, which does not occur in prose. Acceptable, and the test in 4b makes it visible.
- **Self-quarantine.** The one failure that matters. Step 5's committed test is the guard, and the change must not be split across two releases.

## 8. Tests to add

- `tests/test_case_rules.py` — the predicate: two-letter, single common word, single uncommon word, multi-token, hyphenated, possessive, all-caps.
- `tests/test_common_word_names.py` — the end-to-end corpus check from step 5, both pathways, plus the scanned-page case from step 7.
- Additions to `test_filename_redaction.py`, `test_redactor.py` (whole-word matcher branch), `test_ocr_redaction.py` (OCR matcher and fuzzy branch, mocked), `test_text_deidentifier.py` (pattern branch), and one backend test for the review-badge flag.

## 9. Size

Around a day of work, most of it in steps 2, 4 and 5. The behaviour change itself is small because rule 7 already built the machinery; the cost is in proving, on a realistic corpus, that nothing quarantines.
