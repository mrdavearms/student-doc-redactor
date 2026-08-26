import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import tempfile
from pathlib import Path

import fitz
from text_pdf import choose_sentinel, render

BLOCK = '█' * 6


def _render(text):
    path = Path(tempfile.mkdtemp()) / 'out.pdf'
    render(text, path, block=BLOCK)
    return path


def test_no_pii_and_no_sentinel_survive_in_the_saved_pdf():
    path = _render(f'Name: {BLOCK} attended on {BLOCK}.')
    doc = fitz.open(str(path))
    extracted = ''.join(p.get_text() for p in doc)
    doc.close()
    assert 'Name:' in extracted
    assert '█' not in extracted
    assert '?' not in extracted          # the base-14 font failure mode
    for candidate in ['¤', '¦', '¿', '~', '^', '¶', '§']:
        assert candidate not in extracted


def test_black_rectangles_are_actually_drawn():
    path = _render(f'Name: {BLOCK} and {BLOCK}.')
    doc = fitz.open(str(path))
    drawings = doc[0].get_drawings()
    doc.close()
    assert len(drawings) >= 2


def test_the_users_own_text_is_never_boxed():
    # '~' is a sentinel candidate. If the renderer hard-coded it, the tilde in
    # the user's text would be blacked out along with the real redaction.
    path = _render(f'Cost ~5 dollars. Name: {BLOCK}.')
    doc = fitz.open(str(path))
    extracted = ''.join(p.get_text() for p in doc)
    doc.close()
    assert '~5 dollars' in extracted


def test_choose_sentinel_skips_characters_present_in_the_text():
    assert choose_sentinel('Cost ~5 ^ item ¤ ¦') == '¿' * 6


def test_choose_sentinel_falls_back_when_every_candidate_occurs():
    crowded = '¤¦¿~^¶§'
    assert choose_sentinel(crowded) == '[REMOVED]'


def test_choose_sentinel_avoids_collision_with_the_literal_fallback():
    # Every single-character candidate AND the literal fallback marker are
    # already present. A hard-coded '[REMOVED]' fallback would collide with
    # the user's own text — exactly the bug the per-render sentinel exists to
    # prevent, just one level down.
    crowded = '¤¦¿~^¶§[REMOVED]'
    sentinel = choose_sentinel(crowded)
    assert sentinel not in crowded


def test_the_users_own_removed_marker_is_never_boxed():
    # Forces the fallback-collision path end to end: every single-character
    # candidate AND the literal "[REMOVED]" are present in the user's own
    # text. If the fallback sentinel were hard-coded, this literal occurrence
    # would be blacked out along with the real redaction.
    crowded = '¤¦¿~^¶§ the report says [REMOVED] verbatim.'
    path = _render(f'{crowded} Name: {BLOCK}.')
    doc = fitz.open(str(path))
    extracted = ''.join(p.get_text() for p in doc)
    doc.close()
    assert '[REMOVED] verbatim' in extracted


def test_long_text_paginates():
    path = _render('The student was observed in class. ' * 400)
    doc = fitz.open(str(path))
    pages = doc.page_count
    doc.close()
    assert pages > 1


def test_metadata_is_stripped():
    path = _render('Nothing identifying here.')
    doc = fitz.open(str(path))
    meta = doc.metadata
    doc.close()
    assert not meta.get('author')
    assert not meta.get('producer')


def _non_whitespace_count(s):
    """PyMuPDF's own line-wrapping inserts/repositions whitespace on extract,
    so whitespace can't be compared verbatim across a render round-trip --
    but no non-whitespace character may ever be dropped."""
    return len(''.join(s.split()))


def test_a_long_unbroken_token_is_fully_recovered():
    # Regression for defect B: a single token with no whitespace to break on
    # used to hard-split at len(text) // 2 with no check that the split
    # point actually fit, silently rendering zero characters for that chunk.
    long_token = 'supercalifragilisticexpialidocious' * 500  # 17,000 chars
    path = _render(f'Intro sentence.\n{long_token}\nEnd of document.')
    doc = fitz.open(str(path))
    extracted = ''.join(p.get_text() for p in doc)
    doc.close()

    assert 'Intro sentence.' in extracted
    assert 'End of document.' in extracted
    # The whole token must be present -- assert on the actual recovered
    # character count, not merely that pages exist.
    assert _non_whitespace_count(long_token) == 17000
    assert long_token in ''.join(extracted.split())


def test_the_reported_pathological_case_produces_no_blank_page():
    # The exact shape from the e2e report: a normal sentence, then a huge
    # unbroken word, then a real PII value to redact. The unbroken word used
    # to vanish entirely into a blank page between the sentence and the tail.
    long_token = 'supercalifragilisticexpialidocious' * 500
    text = (f'A normal sentence comes first.\n{long_token}\n'
            f'Contact phone: {BLOCK}')
    path = _render(text)
    doc = fitz.open(str(path))
    per_page_chars = [len(p.get_text().strip()) for p in doc]
    extracted = ''.join(p.get_text() for p in doc)
    doc.close()

    assert all(count > 0 for count in per_page_chars), (
        f'a page rendered zero characters: {per_page_chars}')
    # Confirm no content was lost, not just that no page is blank.
    expected_non_ws = _non_whitespace_count(
        text.replace(BLOCK, ''))
    assert _non_whitespace_count(extracted) == expected_non_ws
