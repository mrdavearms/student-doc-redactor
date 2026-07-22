import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import pytest
import fitz  # PyMuPDF
from unittest.mock import patch
from pathlib import Path
import tempfile
from redactor import PDFRedactor, RedactionItem


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


class TestRedactPdfRobustness:
    """redact_pdf must never raise, must close its document, and must not
    leave a partially-written output file behind when a stage fails."""

    def _make_pdf_file(self, path, text="Hello Joe Bloggs"):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), text, fontsize=12)
        doc.save(str(path))
        doc.close()

    def test_failure_returns_false_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.pdf"
            out = Path(tmp) / "out.pdf"
            self._make_pdf_file(src)
            redactor = PDFRedactor()

            def boom(self, doc):
                raise RuntimeError("strip failed")

            with patch.object(PDFRedactor, "_strip_metadata", boom):
                success, msg = redactor.redact_pdf(
                    src, out, [RedactionItem(page_num=1, text="Joe Bloggs")]
                )
            assert success is False
            assert "strip failed" in msg

    def test_partial_output_removed_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.pdf"
            out = Path(tmp) / "out.pdf"
            self._make_pdf_file(src)
            redactor = PDFRedactor()

            def boom(self, doc):
                out.write_bytes(b"%PDF partial")  # simulate a half-written file
                raise RuntimeError("save failed")

            with patch.object(PDFRedactor, "_strip_metadata", boom):
                success, msg = redactor.redact_pdf(
                    src, out, [RedactionItem(page_num=1, text="Joe Bloggs")]
                )
            assert success is False
            assert not out.exists(), "partial output must be removed on failure"

    def test_document_closed_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.pdf"
            out = Path(tmp) / "out.pdf"
            self._make_pdf_file(src)
            redactor = PDFRedactor()
            opened = []
            real_open = fitz.open

            def tracking_open(*a, **k):
                d = real_open(*a, **k)
                opened.append(d)
                return d

            def boom(self, doc):
                raise RuntimeError("boom")

            with patch("redactor.fitz.open", tracking_open), \
                 patch.object(PDFRedactor, "_strip_metadata", boom):
                redactor.redact_pdf(
                    src, out, [RedactionItem(page_num=1, text="Joe Bloggs")]
                )
            assert opened, "redact_pdf should have opened a document"
            assert opened[0].is_closed, "document must be closed after a failure"


class TestWholeWordVerification:
    """Verification must not flag PII 'visible' inside longer ordinary words."""

    def test_helper_no_match_inside_longer_word(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("Ann", "annual review scheduled") is False

    def test_helper_no_match_with_leading_letters(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("Ann", "the banner was red") is False

    def test_helper_matches_whole_word(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("Ann", "ann was here") is True

    def test_helper_matches_possessive(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("Ann", "ann's workbook") is True

    def test_helper_multiword_across_whitespace(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("Sarah Williams", "report for sarah\nwilliams today") is True

    def test_helper_multiword_joined_by_hyphen(self):
        """OCR may join or hyphenate a name — that is still visible PII."""
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("Sarah Williams", "sarah-williams") is True

    def test_helper_hyphenated_name_split_by_spaces(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("Smith-Jones", "smith - jones") is True

    def test_helper_does_not_overmatch_longer_surname(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("Sarah Williams", "sarah williamson") is False

    def test_helper_email_exact(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("nick.williams@gmail.com",
                                    "contact nick.williams@gmail.com now") is True

    def test_helper_apostrophe_name(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("O'Brien", "kate o'brien attended") is True

    def test_verify_redaction_passes_when_name_only_inside_longer_word(self, tmp_path):
        """A correctly-redacted doc containing 'Annual' must verify clean for 'Ann'."""
        import fitz
        from redactor import PDFRedactor, RedactionItem

        src = tmp_path / "ann.pdf"
        out = tmp_path / "ann_redacted.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "Student: Ann Chen", fontsize=12)
        page.insert_text((72, 130), "Annual Review scheduled for Term 3.", fontsize=12)
        doc.save(str(src))
        doc.close()

        r = PDFRedactor()
        ok, _ = r.redact_pdf(src, out, [RedactionItem(page_num=1, text="Ann"),
                                        RedactionItem(page_num=1, text="Chen")])
        assert ok

        is_clean, msg = r.verify_redaction(out, "Ann")
        assert is_clean, f"False positive: {msg}"

    def test_verify_redaction_still_fails_when_name_remains(self, tmp_path):
        import fitz
        from redactor import PDFRedactor

        pdf = tmp_path / "unredacted.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "Student: Ann Chen", fontsize=12)
        doc.save(str(pdf))
        doc.close()

        r = PDFRedactor()
        is_clean, _ = r.verify_redaction(pdf, "Ann")
        assert not is_clean
