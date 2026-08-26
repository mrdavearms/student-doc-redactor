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
