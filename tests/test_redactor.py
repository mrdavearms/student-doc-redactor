import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import pytest
import fitz  # PyMuPDF
from redactor import PDFRedactor


def _make_page_with_text(text: str):
    """Create a single-page in-memory PDF containing the given text."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=12)
    return page, doc


class TestRedactTextSearch:

    def setup_method(self):
        self.redactor = PDFRedactor()

    def test_very_short_text_under_3_chars_is_skipped(self):
        """Text shorter than 3 characters must never be searched or redacted."""
        page, doc = _make_page_with_text("Jo Smith")
        self.redactor._redact_text_search(page, "Jo")
        annots = list(page.annots())
        assert len(annots) == 0, "2-char string should not create redaction annotations"
        doc.close()

    def test_short_text_that_is_not_a_whole_word_is_skipped(self):
        """'Ann' must not be redacted when it only appears inside 'Annual'."""
        page, doc = _make_page_with_text("Annual Review completed.")
        self.redactor._redact_text_search(page, "Ann")
        annots = list(page.annots())
        assert len(annots) == 0, "'Ann' inside 'Annual' should not be redacted"
        doc.close()

    def test_short_text_that_is_a_whole_word_is_redacted(self):
        """'Ann' must be redacted when it appears as a standalone word."""
        page, doc = _make_page_with_text("Ann Smith attended the meeting.")
        self.redactor._redact_text_search(page, "Ann")
        annots = list(page.annots())
        assert len(annots) >= 1, "'Ann' as a standalone word should be redacted"
        doc.close()

    def test_long_text_over_6_chars_redacted_without_word_check(self):
        """Texts longer than 6 chars bypass word-boundary check (low false-match risk)."""
        page, doc = _make_page_with_text("Jennifer Smith attended.")
        self.redactor._redact_text_search(page, "Jennifer")
        annots = list(page.annots())
        assert len(annots) >= 1, "8-char name should be redacted normally"
        doc.close()

    def test_short_whole_word_not_redacted_inside_longer_word_on_same_page(self):
        """When 'Ann' appears both standalone AND inside 'Annual', only standalone is redacted."""
        page, doc = _make_page_with_text("Annual review. Ann Smith attended.")
        self.redactor._redact_text_search(page, "Ann")
        annots = list(page.annots())
        assert len(annots) == 1, f"Expected 1 redaction (standalone 'Ann'), got {len(annots)}"
        doc.close()

    def test_possessive_form_with_straight_apostrophe_is_redacted(self):
        """'Joe's' (straight apostrophe) must be redacted when searching for 'Joe'."""
        page, doc = _make_page_with_text("Joe's behaviour was excellent.")
        self.redactor._redact_text_search(page, "Joe")
        annots = list(page.annots())
        assert len(annots) >= 1, "'Joe' in 'Joe's' should be redacted"
        doc.close()

    def test_possessive_form_with_curly_apostrophe_is_redacted(self):
        """'Joe\u2019s' (curly apostrophe) — the _is_whole_word_match logic handles it,
        but PyMuPDF insert_text may not render \u2019 in the word list.
        Test the matcher directly instead."""
        redactor = PDFRedactor()
        # Simulate word rects: (rect, word_text) — rect doesn't matter for logic test
        import fitz
        fake_rect = fitz.Rect(100, 100, 150, 120)
        word_rects = [(fake_rect, "Joe\u2019s")]
        assert redactor._is_whole_word_match(fake_rect, "Joe", word_rects) is True

    def test_possessive_does_not_match_substring(self):
        """Possessive handling must not cause 'Ann' to match inside 'Annette's'."""
        page, doc = _make_page_with_text("Annette's report was complete.")
        self.redactor._redact_text_search(page, "Ann")
        annots = list(page.annots())
        assert len(annots) == 0, "'Ann' should not match inside 'Annette's'"
        doc.close()

    def test_name_with_trailing_punctuation_is_redacted(self):
        """'Joe,' or 'Joe)' — trailing non-alphanumeric chars should still allow redaction."""
        page, doc = _make_page_with_text("Contact Joe, the student, for details.")
        self.redactor._redact_text_search(page, "Joe")
        annots = list(page.annots())
        assert len(annots) >= 1, "'Joe' followed by comma should be redacted"
        doc.close()

    def test_possessive_with_trailing_comma_is_redacted(self):
        """Regression: 'Joe's,' (possessive + comma) must be redacted.
        Previously rejected because remainder \"'s,\" matched neither the
        possessive check nor the pure-punctuation check."""
        page, doc = _make_page_with_text("collaboratively with Joe's, his parents.")
        self.redactor._redact_text_search(page, "Joe")
        annots = list(page.annots())
        assert len(annots) >= 1, "'Joe' in 'Joe's,' (possessive + comma) should be redacted"
        doc.close()

    def test_possessive_with_trailing_period_is_redacted(self):
        """'Joe's.' (possessive + period) must also be redacted."""
        redactor = PDFRedactor()
        import fitz
        fake_rect = fitz.Rect(100, 100, 150, 120)
        word_rects = [(fake_rect, "Joe's.")]
        assert redactor._is_whole_word_match(fake_rect, "Joe", word_rects) is True
