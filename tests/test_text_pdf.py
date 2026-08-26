import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import tempfile
from pathlib import Path

import fitz
import text_pdf
from text_pdf import choose_sentinel, render, unsupported_characters

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


# ── Defect A: unsupported (non-Latin-1) characters must be reported, not
# silently corrupted to "?" ─────────────────────────────────────────────────

def _render_as_question_mark(char):
    """Ground truth: does this single character actually come out as '?'
    when laid out with the real renderer font? Used to confirm the
    detection helper's predictions against the real rendered result, not
    just against fitz.Font.has_glyph() in isolation."""
    probe = fitz.open()
    page = probe.new_page(width=595, height=842)
    rect = fitz.Rect(50, 50, 545, 792)
    page.insert_textbox(rect, f'X{char}Y', fontname='helv', fontsize=11)
    extracted = page.get_text().strip()
    probe.close()
    if extracted.startswith('X') and extracted.endswith('Y'):
        extracted = extracted[1:-1]
    return extracted == '?'


def test_ordinary_latin1_text_has_no_unsupported_characters():
    assert unsupported_characters('Café François Müller Zoë - 100%!') == []


def test_whitespace_is_never_reported_as_unsupported():
    assert unsupported_characters('line one\nline two\ttabbed') == []


def test_emoji_hebrew_chinese_and_arabic_are_detected_as_unsupported():
    text = 'Great work! 🎉 שלום 你好 مرحبا'
    found = unsupported_characters(text)
    assert '🎉' in found
    assert 'ש' in found
    assert '你' in found
    assert 'م' in found


def test_characters_that_LOOK_covered_but_actually_render_as_question_mark():
    # These exist in the underlying font FILE (fitz.Font.has_glyph() alone
    # would call them "supported"), but a base-14 font is written into the
    # PDF as a single-byte Latin-1 font, so MuPDF can never actually reach
    # them -- confirmed by direct rendering. Regression for trusting
    # has_glyph() in isolation.
    for char in ['€', '—', '–', '‘', '’', '“', '”', 'œ']:
        assert _render_as_question_mark(char), (
            f'test premise wrong: {char!r} did not render as "?"')
        assert char in unsupported_characters(f'text {char} text'), (
            f'{char!r} renders as "?" but was not detected as unsupported')


def test_detection_helper_agrees_with_real_rendered_output():
    # Broad cross-check: for a sample spanning printable ASCII, the full
    # Latin-1 supplement, Latin Extended-A, common "looks covered but isn't"
    # punctuation, and a few emoji/CJK/Hebrew/Arabic characters, the helper's
    # prediction must match what actually gets rendered.
    codepoints = (list(range(0x20, 0x7F)) + list(range(0xA0, 0x180))
                  + [0x20AC, 0x2014, 0x2013, 0x2018, 0x2019, 0x201C, 0x201D,
                     0x1F600, 0x05D0, 0x4F60, 0x0645])
    mismatches = []
    for cp in codepoints:
        char = chr(cp)
        if char.isspace() or char == '?':
            continue  # a literal '?' can't be told apart from a substitution
        predicted_unsupported = char in unsupported_characters(f'x{char}y')
        actually_renders_as_q = _render_as_question_mark(char)
        if predicted_unsupported != actually_renders_as_q:
            mismatches.append((hex(cp), char, predicted_unsupported, actually_renders_as_q))
    assert mismatches == []


def test_the_block_marker_itself_is_never_reported_as_unsupported():
    # U+2588 (the block character) is not Latin-1 and would fail the glyph
    # check on its own -- but render() never actually inserts it into the
    # page (it becomes the sentinel first, then gets redacted away), so it
    # must never appear in the reported list.
    warnings = render(f'Name: {BLOCK}.', _tmp_path(), block=BLOCK)
    assert '█' not in warnings


def _tmp_path():
    return Path(tempfile.mkdtemp()) / 'out.pdf'


def test_render_reports_no_warnings_for_ordinary_text():
    warnings = render(f'Name: {BLOCK} attended school today.', _tmp_path(), block=BLOCK)
    assert warnings == []


def test_render_reports_unsupported_characters_found_in_the_users_own_text():
    warnings = render(f'Great effort! 🎉 Name: {BLOCK}.', _tmp_path(), block=BLOCK)
    assert '🎉' in warnings
    # The redacted PII itself must still be gone, and the save must still
    # succeed (a warning is not a failure) -- proven by _render() not raising.


def test_render_still_saves_successfully_despite_unsupported_characters():
    # The save must succeed even when content can't be fully displayed --
    # a partly-imperfect PDF the user is warned about beats a refused save.
    path = _tmp_path()
    render(f'Notes: 你好 Name: {BLOCK}.', path, block=BLOCK)
    doc = fitz.open(str(path))
    extracted = ''.join(p.get_text() for p in doc)
    doc.close()
    assert 'Notes:' in extracted
    assert '█' not in extracted


# ── Follow-up: common typographic characters must be transliterated, not
# just warned about, because Word/web pastes produce them by default ────────

def test_the_reported_sentence_renders_with_no_question_marks():
    # The exact coordinator-reported sentence: a curly apostrophe, curly
    # double quotes, an em dash, and an ellipsis -- the near-default case
    # for text pasted out of Word, not an edge case. Before this fix every
    # one of these five characters rendered as a literal "?".
    text = ('The student’s report — “excellent progress” '
            '… was filed.')
    path = _render(f'{text} Name: {BLOCK}.')
    doc = fitz.open(str(path))
    extracted = ''.join(p.get_text() for p in doc)
    doc.close()

    assert '?' not in extracted
    assert "student's report" in extracted
    assert '"excellent progress"' in extracted
    assert '-' in extracted    # em dash -> a hyphen-based substitute
    assert '...' in extracted  # ellipsis -> three dots
    assert '█' not in extracted


def test_common_typography_is_no_longer_flagged_as_unsupported():
    # These used to show up in render()'s warning list on almost every
    # save (Word/web auto-substitute them); they must now be silently
    # fixed instead, so the warning is reserved for genuinely undisplayable
    # content (non-Latin scripts, emoji).
    text = '‘quoted’ “text” – an em—dash … • point €5 ™'
    warnings = render(text, _tmp_path(), block=BLOCK)
    assert warnings == []


def test_sentinel_is_chosen_after_transliteration_not_before():
    """
    Regression for the ordering trap. choose_sentinel() must inspect the
    ALREADY-TRANSLITERATED text -- not the raw text -- because its whole
    contract is "absent from the exact string about to be laid out and
    later searched for".

    Forces the scenario with a throwaway transliteration entry (a snowman
    character mapped to six '¤' -- matching choose_sentinel()'s default
    width and its first-preference candidate) so the trap fires
    deterministically regardless of what the real table contains today:

    - If sentinel selection ran on the PRE-transliteration text (the bug),
      '¤' looks absent and gets chosen as the sentinel. Transliteration then
      introduces exactly '¤¤¤¤¤¤' into the user's own content, and
      apply_redactions() blacks it out as if it were a real block run --
      silently destroying legitimate content, the exact failure mode
      choose_sentinel()'s docstring exists to prevent.
    - Run in the correct order (transliterate, then choose), '¤' is no
      longer absent once the substitution has happened, so a later
      candidate is chosen instead and the user's content survives intact.
    """
    monkeypatch_key = '☃'  # snowman -- not a realistic paste character,
    # chosen only so this test doesn't depend on anything already in
    # TRANSLITERATIONS today.
    original = dict(text_pdf.TRANSLITERATIONS)
    text_pdf.TRANSLITERATIONS[monkeypatch_key] = '¤' * 6
    try:
        text = f'Code: {monkeypatch_key} recorded. Name: {BLOCK}.'
        path = _render(text)
        doc = fitz.open(str(path))
        extracted = ''.join(p.get_text() for p in doc)
        drawings = doc[0].get_drawings()
        doc.close()

        assert '¤¤¤¤¤¤' in extracted, (
            'the introduced content was blacked out -- sentinel was chosen '
            'before transliteration ran')
        assert 'Code:' in extracted and 'recorded' in extracted
        # Only the real block run was redacted, not the introduced '¤'s.
        assert len(drawings) == 1
    finally:
        text_pdf.TRANSLITERATIONS.clear()
        text_pdf.TRANSLITERATIONS.update(original)
