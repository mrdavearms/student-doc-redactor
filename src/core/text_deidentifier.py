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

from redactor import _PII_SEP, _pii_visible_in_text, fuzzy_word_match


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
    tokens = [re.escape(t) for t in re.split(_PII_SEP + r"+", pii_text.lower()) if t]
    if not tokens:
        return ''
    return (_PII_SEP + r"*").join(tokens)


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
        unique.setdefault(raw.lower(), (raw, getattr(match, 'category', '')))

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
    haystack = strip_labels(text, labels).lower()
    return [
        pii for pii in selected_texts
        if pii and len(pii.strip()) >= 3 and _pii_visible_in_text(pii.strip(), haystack)
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
            if any(fuzzy_word_match(word, token) for word in words):
                leftovers.append(pii.strip())
                break
    return leftovers
