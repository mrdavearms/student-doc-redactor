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

One exception to NOT_LOWERCASE: a word the teacher ADDED BY HAND in all
lowercase ("grace") has been declared the name as written, so for that run it
is IGNORE. The redact, de-identify and paste-clean endpoints set it with
any_case_for(); it lasts for that request only.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from common_words import COMMON_WORDS

EXACT = 'exact'
NOT_LOWERCASE = 'not_lowercase'
IGNORE = 'ignore'

EXACT_MAX_LEN = 2

# Lowercased common words matched in any case for the current request.
_ANY_CASE: ContextVar[frozenset] = ContextVar('case_rules_any_case', default=frozenset())


def case_mode(text: str) -> str:
    """The case rule for one PII string."""
    t = (text or '').strip()
    if len(t) <= EXACT_MAX_LEN:
        return EXACT
    # isalpha() is False for spaces, hyphens, apostrophes and digits, so only
    # a single plain word can be an ordinary word.
    if t.isalpha() and t.lower() in COMMON_WORDS and t.lower() not in _ANY_CASE.get():
        return NOT_LOWERCASE
    return IGNORE


def is_lowercase_manual_word(text: str, source: str) -> bool:
    """A common word the teacher typed in by hand, in all lowercase."""
    t = (text or '').strip()
    return source == 'manual' and t.islower() and case_mode(t) == NOT_LOWERCASE


@contextmanager
def any_case_for(words):
    """Match these common words in any case until the block ends."""
    token = _ANY_CASE.set(frozenset(w.strip().lower() for w in words))
    try:
        yield
    finally:
        _ANY_CASE.reset(token)


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


def is_common_word_name(text: str) -> bool:
    """Whether this PII string is a NOT_LOWERCASE name. Drives the review
    screen's "common word" badge."""
    return case_mode(text or '') == NOT_LOWERCASE


def has_common_word_name(texts) -> bool:
    """Whether any of these PII strings is a NOT_LOWERCASE name."""
    return any(is_common_word_name(t) for t in texts)
