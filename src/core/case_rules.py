"""
How a PII string is matched against case — decided here, and only here.

Detection, text-layer redaction, OCR redaction, both redaction verifiers and
de-identification all ask this module. If any one of them answered differently,
it would either offer rows the redactor never acts on, or report a correctly
redacted name as "still visible" and quarantine the file (rules 7 and 7a in
CLAUDE.md).

Three modes:

- EXACT: two characters or fewer. "Do" the surname is never "do" the verb.
- NOT_LOWERCASE: a single word that is also an ordinary English word ("Will",
  "Young", "Grace", "Long"). It matches in any case EXCEPT entirely lowercase:
  "Young", "YOUNG" and "Young's" are the name, "young" is the word. Rule 11a
  redacts a selected string on every page, so without this a teacher could not
  keep "young people" by unticking it.
- IGNORE: everything else, including every multi-word string ("Will Young").
"""

from common_words import COMMON_WORDS

EXACT = 'exact'
NOT_LOWERCASE = 'not_lowercase'
IGNORE = 'ignore'

EXACT_MAX_LEN = 2


def case_mode(text: str) -> str:
    """The case rule for one PII string."""
    t = (text or '').strip()
    if len(t) <= EXACT_MAX_LEN:
        return EXACT
    # isalpha() is False for spaces, hyphens, apostrophes and digits, so only
    # a single plain word can be an ordinary word.
    if t.isalpha() and t.lower() in COMMON_WORDS:
        return NOT_LOWERCASE
    return IGNORE


def case_allows(pii_text: str, found: str) -> bool:
    """
    Whether `found`, an occurrence already matched ignoring case, counts as
    `pii_text`. Only the NOT_LOWERCASE rule is applied here; EXACT strings are
    matched case-sensitively by the caller in the first place.

    `found` may carry what the matcher kept around the word — a possessive,
    a comma, quotes — none of which changes whether it is all lowercase.
    """
    return not (case_mode(pii_text) == NOT_LOWERCASE and found.islower())


# Appended to the scanned-page warning in both pathways when a selected name
# is a common word. A poor scan can read "Young" as "young"; that word is then
# left alone by the OCR redactor and, consistently, not reported by the OCR
# verifier. Accepted rather than special-cased, so it is said out loud. No
# example names, not even made-up ones: a student may be called Grace, and the
# de-identify audit log must not contain a real name.
SCANNED_PAGE_NOTE = (
    "A name that is also an everyday word is only removed where the scan "
    "shows it with a capital letter. Check the scanned pages for one the scan "
    "read in lowercase."
)


def has_common_word_name(texts) -> bool:
    """Whether any of these PII strings is a NOT_LOWERCASE name."""
    return any(case_mode(t or '') == NOT_LOWERCASE for t in texts)
