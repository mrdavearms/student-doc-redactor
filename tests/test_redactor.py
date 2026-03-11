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
