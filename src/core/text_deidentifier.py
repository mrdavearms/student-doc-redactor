"""
Text De-identifier
Replaces detected PII in extracted document text with non-identifying labels.

Unlike redaction, the text produced here IS the deliverable — it is what the
user pastes into an AI tool. That raises the stakes on two things: every
selected item must actually be replaced, and a name the OCR misread must not
slip through readable.
"""

import re
from typing import Dict, List, Tuple

from case_rules import NOT_LOWERCASE, case_mode
from redactor import _PII_SEP, _is_case_sensitive_pii, _pii_visible_in_text, fuzzy_word_match


# A match must not start or end inside a longer alphanumeric run. Plain \b
# fails for variations that begin or end with punctuation ("J. Smith", "S.W."),
# which is why the orchestrator uses lookarounds too.
_LEFT_BOUNDARY = r'(?<![A-Za-z0-9])'
_RIGHT_BOUNDARY = r'(?![A-Za-z0-9])'


def _pattern_for(pii_text: str) -> str:
    """
    Pattern matching one PII string, tolerating the separator variations OCR
    introduces ("Smith - Jones", "smithjones").

    Deliberately mirrors the token handling in redactor._pii_visible_in_text so
    that anything verification would flag as still visible is something this
    pattern would have replaced. If the two drifted apart, correctly processed
    files would start quarantining themselves.
    """
    # Two-letter PII is matched as written even though the combined pattern is
    # compiled IGNORECASE: "(?-i:Do)" replaces the surname Do, not every "do".
    if _is_case_sensitive_pii(pii_text):
        return '(?-i:' + _any_apostrophe(re.escape(pii_text.strip())) + ')'
    # A name that is also an ordinary word matches in any case except all
    # lowercase: "Young" and "YOUNG" are the name, "young" is the word. The
    # lookahead refuses the exact lowercase spelling; the rest matches as usual.
    if case_mode(pii_text) == NOT_LOWERCASE:
        word = re.escape(pii_text.strip().lower())
        return '(?!(?-i:' + word + '))' + word
    tokens = [_any_apostrophe(re.escape(t))
              for t in re.split(_PII_SEP + r"+", pii_text.lower()) if t]
    if not tokens:
        return ''
    return (_PII_SEP + r"*").join(tokens)


_APOSTROPHES = "['’‘]"


def _any_apostrophe(escaped_token: str) -> str:
    """
    Let an apostrophe in the PII match either form in the text. Detection
    reports "O'Brien" (it normalises to straight quotes) while the extracted
    text still says "O’Brien", and the output must keep the text's own
    characters — so the PATTERN is made tolerant rather than the text folded.
    """
    return re.sub("['’‘]", lambda _: _APOSTROPHES, escaped_token)


def deidentify_text(text: str, selected_matches: List, pmap) -> Tuple[str, int]:
    """
    Replace every selected PII string in `text` with its label.

    Args:
        text: The extracted document text.
        selected_matches: PIIMatch objects the user chose to remove.
        pmap: A PseudonymMap providing the label for each item.

    Returns:
        (de-identified text, number of replacements made)
    """
    if not text or not selected_matches:
        return text, 0

    # One entry per distinct string. The first category seen wins — only
    # structured PII consults the category at all, and a string that detects as
    # two categories is the same value either way.
    unique: Dict[str, Tuple[str, str]] = {}
    for match in selected_matches:
        raw = (getattr(match, 'text', '') or '').strip()
        if len(raw) < 2:
            continue
        category = getattr(match, 'category', '')
        # The map is the authority on what is a person; ask it before replacing
        # a contextual guess like the word "Phone" with "[name]".
        if not pmap.should_replace(raw, category):
            continue
        unique.setdefault(raw.lower(), (raw, category))

    if not unique:
        return text, 0

    # Longest first, so "Billy Bob" is consumed before a lone "Billy" can split
    # it into "[Student] Bob".
    ordered = sorted(unique.values(), key=lambda pair: len(pair[0]), reverse=True)

    alternatives = []
    labels = []
    for i, (raw, category) in enumerate(ordered):
        pattern = _pattern_for(raw)
        if not pattern:
            continue
        alternatives.append(f'(?P<g{len(labels)}>{pattern})')
        labels.append(pmap.label_for(raw, category))

    if not alternatives:
        return text, 0

    # ONE pass over the text. A second pass could match inside a label already
    # inserted — a student actually named "Person" would turn "[Person 1]" into
    # "[[Student] 1]" — and single-pass alternation also gives longest-first
    # precedence for free, since alternatives are ordered by length.
    combined = re.compile(
        _LEFT_BOUNDARY + r'(?:' + '|'.join(alternatives) + r')' + _RIGHT_BOUNDARY,
        re.IGNORECASE,
    )

    count = 0

    def _replace(mo: 're.Match') -> str:
        nonlocal count
        count += 1
        return labels[int(mo.lastgroup[1:])]

    return combined.sub(_replace, text), count


def strip_labels(text: str, labels=None) -> str:
    """
    Remove our own inserted labels before verifying.

    Without this, a person genuinely named "Person" would see the label
    "[Person 1]" reported as their name still being visible, quarantining a
    correctly processed file. Only the exact label strings are removed, so
    square brackets that were in the source document still get checked.
    """
    if not text or not labels:
        return text or ''
    pattern = re.compile(
        '|'.join(re.escape(l) for l in sorted(labels, key=len, reverse=True))
    )
    return pattern.sub(' ', text)


def verify_deidentified(text: str, selected_texts: List[str], labels=None) -> List[str]:
    """
    PII strings still visible in the output, using the same whole-word check as
    redaction verification (never substring — 'Ann' inside 'Annual' is not a
    leak).
    """
    haystack = strip_labels(text, labels)
    return [
        pii for pii in selected_texts
        if pii and len(pii.strip()) >= 2 and _pii_visible_in_text(pii.strip(), haystack)
    ]


def fuzzy_leftovers(text: str, selected_texts: List[str], labels=None) -> List[str]:
    """
    Near-miss PII surviving in text that came from OCR.

    In redaction a garbled OCR word only means a black box lands imperfectly.
    Here the OCR text is the deliverable, so "Bi11y" would ship readable. Uses
    the identical tolerance rule as OCR redaction (alphabetic, 5+ characters,
    distance 1 up to 7 letters and 2 beyond).
    """
    if not text:
        return []

    words = {
        re.sub(r"[^\w'’]", '', w).lower()
        for w in re.split(r'\s+', strip_labels(text, labels))
    }
    words.discard('')

    leftovers = []
    for pii in selected_texts:
        for token in re.split(_PII_SEP + r"+", (pii or '').strip().lower()):
            if not token.isalpha() or len(token) < 5:
                continue
            # "Kew Primary School" must not flag every later "school", nor
            # "12 Smith Street" every "street".
            if token in _FUZZY_GENERIC_TOKENS:
                continue
            # An exact hit on ONE token of a multi-word value is not a near
            # miss of the value; whole-value visibility is verify_deidentified's
            # job, and a lone surname the user left unticked is their call.
            if any(word != token and fuzzy_word_match(word, token) for word in words):
                leftovers.append(pii.strip())
                break
    return leftovers


_FUZZY_GENERIC_TOKENS = {
    'school', 'primary', 'secondary', 'college', 'clinic', 'centre', 'center',
    'hospital', 'practice', 'academy', 'institute', 'university', 'department',
    'service', 'services', 'psychology', 'medical', 'health', 'group', 'street',
    'road', 'avenue', 'drive', 'court', 'place', 'lane', 'crescent', 'boulevard',
    'terrace', 'close', 'grove', 'highway', 'parade', 'circuit', 'esplanade',
    'north', 'south', 'east', 'west', 'upper', 'lower', 'state', 'public',
    'catholic', 'christian', 'grammar', 'anglican', 'community', 'family',
    'children', 'learning', 'support', 'education', 'district', 'regional',
}
