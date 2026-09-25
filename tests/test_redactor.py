import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import pytest
import fitz  # PyMuPDF
from unittest.mock import patch
from pathlib import Path
import tempfile
from redactor import PDFRedactor, RedactionItem, _pii_visible_in_text


def _make_page_with_text(text: str):
    """Create a single-page in-memory PDF containing the given text."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=12)
    return page, doc


class TestRedactTextSearch:

    def setup_method(self):
        self.redactor = PDFRedactor()

    def test_single_character_text_is_skipped(self):
        """A single character must never be searched or redacted."""
        page, doc = _make_page_with_text("J Smith")
        self.redactor._redact_text_search(page, "J")
        assert len(list(page.annots())) == 0
        doc.close()

    def test_two_char_name_is_redacted_when_case_matches(self):
        """'Jo' is a real name and must be blacked out (whole word, as written)."""
        page, doc = _make_page_with_text("Jo Smith joined. Jo's work. jo")
        self.redactor._redact_text_search(page, "Jo")
        # "Jo" and "Jo's" match; the lowercase "jo" does not
        assert len(list(page.annots())) == 2
        doc.close()

    def test_two_char_name_does_not_match_the_english_word(self):
        """The surname 'Do' must never black out the verb 'do'."""
        page, doc = _make_page_with_text("We do our best. do it.")
        self.redactor._redact_text_search(page, "Do")
        assert len(list(page.annots())) == 0
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


class TestHyphenatedWords:
    """PyMuPDF splits words on whitespace only, so "LONG-TERM" is one word.
    The verifier treats the hyphen as a word break and sees the surname Long;
    the redactor must agree, or the file quarantines itself."""

    def test_name_inside_a_hyphenated_word_is_redacted_and_verifies(self, tmp_path):
        src = tmp_path / "report.pdf"
        out = tmp_path / "report_redacted.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "LONG-TERM GOALS", fontsize=12)
        page.insert_text((72, 130), "Mrs Long attended.", fontsize=12)
        doc.save(str(src))
        doc.close()

        r = PDFRedactor()
        ok, _ = r.redact_pdf(src, out, [RedactionItem(page_num=1, text="Long")])
        assert ok
        is_clean, msg = r.verify_redaction(out, "Long")
        assert is_clean, msg
        with fitz.open(str(out)) as d:
            text = d[0].get_text()
        assert "TERM GOALS" in text

    def test_name_inside_a_longer_hyphenated_word_is_not_matched(self):
        page, doc = _make_page_with_text("A self-belonging task.")
        PDFRedactor()._redact_text_search(page, "Long")
        assert len(list(page.annots())) == 0
        doc.close()


class TestDocumentWideRedaction:
    """A selected text is redacted on every page, not only where it was detected.

    Detection runs per page, and NER can tag a name on one page while missing
    it on another. Verification checks the whole document, so a per-page
    redaction left the name readable and quarantined the file as UNVERIFIED.
    """

    def _two_page_pdf(self, path, page1, page2):
        doc = fitz.open()
        for text in (page1, page2):
            page = doc.new_page()
            page.insert_text((72, 100), text, fontsize=12)
        doc.save(str(path))
        doc.close()

    def test_text_detected_on_page_two_is_also_removed_from_page_one(self, tmp_path):
        src = tmp_path / "report.pdf"
        out = tmp_path / "report_redacted.pdf"
        self._two_page_pdf(src, "Ms Priya Raman observed the class.", "Signed: P. Raman")

        r = PDFRedactor()
        ok, _ = r.redact_pdf(src, out, [RedactionItem(page_num=2, text="Raman")])
        assert ok

        doc = fitz.open(str(out))
        texts = [page.get_text() for page in doc]
        doc.close()
        assert "Raman" not in texts[0], "page 1 still shows the name selected on page 2"
        assert "Raman" not in texts[1]
        assert "Priya" in texts[0], "unselected text must be left alone"

        is_clean, msg = r.verify_redaction(out, "Raman")
        assert is_clean, msg

    def test_bbox_item_is_still_applied_on_its_own_page(self, tmp_path):
        src = tmp_path / "report.pdf"
        out = tmp_path / "report_redacted.pdf"
        self._two_page_pdf(src, "Student: Ann Chen", "Nothing here.")

        doc = fitz.open(str(src))
        rect = doc[0].search_for("Chen")[0]
        doc.close()

        r = PDFRedactor()
        ok, _ = r.redact_pdf(
            src, out,
            [RedactionItem(page_num=1, text="Chen", bbox=(rect.x0, rect.y0, rect.x1, rect.y1))],
        )
        assert ok
        doc = fitz.open(str(out))
        assert "Chen" not in doc[0].get_text()
        assert "Nothing here." in doc[1].get_text()
        doc.close()


_TRUETYPE = next((p for p in [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
] if os.path.exists(p)), None)


class TestApostrophesAndQuotes:

    def test_curly_apostrophe_surname_is_redacted(self, tmp_path):
        """Word writes O’Brien (U+2019); detection reports O'Brien. Both must
        be found, or the surname stays readable and the file is quarantined."""
        if not _TRUETYPE:
            pytest.skip("needs a TrueType font: the base-14 fonts cannot encode U+2019")
        src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_font(fontname="tt", fontfile=_TRUETYPE)
        page.insert_text((72, 100), "Siobhan O\u2019Brien reads well. O\u2019Brien is kind.",
                         fontsize=11, fontname="tt")
        doc.save(str(src))
        doc.close()

        r = PDFRedactor()
        ok, _ = r.redact_pdf(src, out, [RedactionItem(1, "O'Brien"),
                                        RedactionItem(1, "Siobhan O'Brien")])
        assert ok
        text = fitz.open(str(out))[0].get_text()
        assert "Brien" not in text
        assert r.verify_redaction(out, "O'Brien")[0]

    def test_visibility_check_folds_apostrophes(self):
        from redactor import _pii_visible_in_text
        assert _pii_visible_in_text("O'Brien", "Ms O\u2019Brien attended")
        assert _pii_visible_in_text("O\u2019Brien", "Ms O'Brien attended")

    def test_short_name_in_quotes_or_brackets_is_redacted(self):
        """PyMuPDF's word list keeps the quotes: ("Joe") is one word."""
        page, doc = _make_page_with_text('Joseph ("Joe") Bloggs, [Joe], Joe. Joel and major stay.')
        r = PDFRedactor()
        r._redact_text_search(page, "Joe")
        page.apply_redactions()
        text = page.get_text()
        assert "Joe" not in text.replace("Joel", "")
        assert "Joel" in text and "major" in text
        doc.close()


class TestRedactionRectPadding:

    def test_tight_line_spacing_keeps_neighbouring_lines_intact(self, tmp_path):
        """search_for returns the font's full line box, which at single
        spacing already overlaps the lines above and below; padding it
        vertically deleted letters from them."""
        src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
        doc = fitz.open()
        page = doc.new_page()
        y = 100
        for line in ["Sarah has made progress in maths.",
                     "Sarah enjoys reading with Sarah.",
                     "Her reading is at level 22."]:
            page.insert_text((72, y), line, fontsize=11)
            y += 12
        doc.save(str(src))
        doc.close()

        ok, _ = PDFRedactor().redact_pdf(src, out, [RedactionItem(1, "Sarah")])
        assert ok
        text = fitz.open(str(out))[0].get_text()
        assert "Sarah" not in text
        assert "has made progress in maths." in text
        assert "enjoys reading with" in text
        assert "Her reading is at level 22." in text


class TestCommonWordNames:
    """A name that is also an ordinary word ("Young", "Long", "Patience")
    matches in any case except all lowercase (case_rules, rule 7a)."""

    def test_lowercase_word_is_left_alone(self):
        page, doc = _make_page_with_text("Mr Young met young people. YOUNG. Young's, young's")
        PDFRedactor()._redact_text_search(page, "Young")
        # "Young", "YOUNG" and "Young's," are the name; the two lowercase are words.
        assert len(list(page.annots())) == 3
        doc.close()

    def test_rule_applies_to_long_words_too(self):
        """Words over six letters skip the whole-word check for ordinary
        names; a common-word name must not, or "patience" is blacked out."""
        page, doc = _make_page_with_text("Patience showed patience.")
        PDFRedactor()._redact_text_search(page, "Patience")
        assert len(list(page.annots())) == 1
        doc.close()

    def test_verifier_ignores_the_lowercase_word(self):
        assert not _pii_visible_in_text("Young", "young people and younger ones")
        assert _pii_visible_in_text("Young", "Mr Young")
        assert _pii_visible_in_text("Young", "STUDENT: YOUNG")
        assert _pii_visible_in_text("Young", "Young's book")
        assert not _pii_visible_in_text("Young", "young's book")

    def test_any_case_ignores_the_rule(self):
        assert _pii_visible_in_text("Young", "young people", any_case=True)
        assert _pii_visible_in_text("Li", "li's mum", any_case=True)

    def test_redact_then_verify_leaves_words_and_passes(self, tmp_path):
        src = tmp_path / "report.pdf"
        out = tmp_path / "report_redacted.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "Mr Young says young people need long breaks.", fontsize=12)
        page.insert_text((72, 130), "Mrs Long agreed. LONG-TERM goals; a long-term aim.", fontsize=12)
        doc.save(str(src))
        doc.close()

        r = PDFRedactor()
        ok, _ = r.redact_pdf(src, out, [RedactionItem(page_num=1, text="Young"),
                                        RedactionItem(page_num=1, text="Long")])
        assert ok
        with fitz.open(str(out)) as d:
            text = d[0].get_text()
        assert "young people" in text and "long breaks" in text and "long-term aim" in text
        assert "Young" not in text and "Long" not in text and "LONG" not in text
        for name in ("Young", "Long"):
            is_clean, msg = r.verify_redaction(out, name)
            assert is_clean, msg
