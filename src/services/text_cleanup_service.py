"""
Text Cleanup Service
Blackout and de-identification over a STRING rather than a document.

Backs the paste-text pathway. Nothing here touches the filesystem: the caller
gets strings back and decides whether they are ever saved.
"""

from typing import List, Tuple

from src.core.text_deidentifier import deidentify_text, verify_deidentified

BLOCK_CHAR = '█'
BLOCK_WIDTH = 6
BLOCK = BLOCK_CHAR * BLOCK_WIDTH


class BlackoutMap:
    """
    Stands in for PseudonymMap in the blackout pathway.

    deidentify_text() reaches its map through exactly two methods, so a
    constant-returning adapter inherits longest-first ordering, the single-pass
    re-match guard and boundary handling for free.

    should_replace() is unconditionally True, deliberately diverging from
    PseudonymMap (CLAUDE.md rule 58). That guard exists to stop a contextual
    false positive rewriting a "Phone:" row into "[name]: [phone]", which is a
    MEANING failure in de-identify mode. A black box over the word "Phone"
    costs nothing, and rule 54a already establishes over-removal as the correct
    bias for the redact pathway.

    Block width is FIXED. A length-matched block leaks the size of what was
    removed — "██" is visibly a short first name.
    """

    def should_replace(self, text: str, category: str) -> bool:
        return True

    def label_for(self, text: str, category: str) -> str:
        return BLOCK


def blackout(text: str, selected_matches: List) -> Tuple[str, int, List[str]]:
    """
    Replace every selected PII string with a fixed-width block run.

    Returns (cleaned text, replacements made, PII still visible). The leftover
    check strips the inserted blocks first, exactly as de-identify verification
    strips its labels.
    """
    cleaned, count = deidentify_text(text, selected_matches, BlackoutMap())
    selected_texts = [
        (getattr(m, 'text', '') or '').strip() for m in selected_matches
    ]
    leftovers = verify_deidentified(cleaned, selected_texts, labels=[BLOCK])
    return cleaned, count, leftovers


def deidentify_paste(text: str, selected_matches: List, pmap) -> Tuple[str, int, List[str]]:
    """
    Replace every selected PII string with its role label.

    The replaced set is derived from pmap.should_replace() and BOTH the
    replacement and the verification read from it. Verifying a string the
    replacer deliberately left alone reports it "still visible" and would
    quarantine correct output — the replace/verify symmetry of CLAUDE.md
    rules 49 and 58.

    No fuzzy pass. Rule 45's tolerance exists for OCR text; pasted text is
    typed, so a classmate "Smyth" against student "Smith" is edit-distance 1
    and would be a false leftover.
    """
    replaced = [
        m for m in selected_matches
        if pmap.should_replace(
            (getattr(m, 'text', '') or '').strip(),
            getattr(m, 'category', ''))
    ]
    cleaned, count = deidentify_text(text, selected_matches, pmap)

    # Same convention as deidentification_service.py: the strip-list before
    # verification is every label the map can emit, not just the ones used
    # here — narrower sets omit category/fallback labels that genuinely land
    # in the output, which verify would then misread as a leftover.
    labels = pmap.all_labels()
    selected_texts = [(getattr(m, 'text', '') or '').strip() for m in replaced]
    leftovers = verify_deidentified(cleaned, selected_texts, labels=labels)
    return cleaned, count, leftovers
