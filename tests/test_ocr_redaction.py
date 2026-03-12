"""
Tests for OCR-based image redaction of scanned/image-only PDF pages.

Covers:
- _is_image_only_page() detection logic
- _redact_ocr_page() word matching (single, multi-word, possessive, punctuation)
- redact_pdf() routing: image-only pages → OCR path, text pages → standard path
- Service layer: OCR items no longer skipped from redaction or verification
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import io
import re
import pytest
import fitz  # PyMuPDF
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image, ImageDraw, ImageFont

from redactor import PDFRedactor, RedactionItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_text_page(text: str):
    """Create a single-page PDF with native text (NOT image-only)."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=12)
    return page, doc


def _make_image_only_page(words=None, width=612, height=792):
    """
    Create a single-page PDF that is image-only (no text layer).

    Inserts a full-page image so _is_image_only_page() returns True.
    The actual OCR of this image is mocked in tests — we only need the
    page structure to be correct (no text words, has images).

    Args:
        words: Ignored here — OCR output is mocked in tests.
        width: Page width in points.
        height: Page height in points.

    Returns:
        (page, doc) tuple.
    """
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)

    # Create a simple white image and insert it as a full-page image
    img = Image.new("RGB", (int(width * 2), int(height * 2)), "white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    page.insert_image(page.rect, stream=buf.read())

    return page, doc


def _make_image_pdf_with_text(text: str, tmp_path: Path) -> Path:
    """
    Create a PDF file containing only an image (no native text layer).
    The image has `text` drawn on it so Tesseract can OCR it.

    Returns the path to the saved PDF.
    """
    # Create an image with text drawn on it
    img = Image.new("RGB", (1200, 800), "white")
    draw = ImageDraw.Draw(img)
    # Use a basic font — PIL default if no system font available
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 40)
    except Exception:
        font = ImageFont.load_default()
    draw.text((50, 50), text, fill="black", font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    # Create PDF with just this image
    doc = fitz.open()
    page = doc.new_page(width=612, height=400)
    page.insert_image(page.rect, stream=buf.read())

    pdf_path = tmp_path / "image_only.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _make_hybrid_page(text_content="Some text", image_width=400, image_height=300):
    """
    Create a single-page PDF with BOTH native text AND an embedded image.

    This simulates the real-world case where a page has text-layer content
    (so _is_image_only_page returns False) but also has an embedded image
    that may contain PII (e.g. an email screenshot).

    Returns:
        (page, doc) tuple.
    """
    doc = fitz.open()
    page = doc.new_page()
    # Add native text layer
    page.insert_text((72, 100), text_content, fontsize=12)
    # Add an embedded image
    img = Image.new("RGB", (image_width, image_height), "white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    page.insert_image(fitz.Rect(50, 200, 50 + image_width // 2, 200 + image_height // 2), stream=buf.read())
    return page, doc


# ---------------------------------------------------------------------------
# _is_image_only_page tests
# ---------------------------------------------------------------------------

class TestIsImageOnlyPage:

    def setup_method(self):
        self.redactor = PDFRedactor()

    def test_text_page_returns_false(self):
        """A page with native text should NOT be detected as image-only."""
        page, doc = _make_text_page("Hello World")
        assert self.redactor._is_image_only_page(page) is False
        doc.close()

    def test_blank_page_returns_false(self):
        """A blank page (no text, no images) should NOT be image-only."""
        doc = fitz.open()
        page = doc.new_page()
        assert self.redactor._is_image_only_page(page) is False
        doc.close()

    def test_image_only_page_returns_true(self):
        """A page with images but no text should be detected as image-only."""
        page, doc = _make_image_only_page()
        assert self.redactor._is_image_only_page(page) is True
        doc.close()

    def test_hybrid_page_returns_false(self):
        """A page with both text and images should NOT be image-only."""
        doc = fitz.open()
        page = doc.new_page()
        # Add text
        page.insert_text((72, 100), "Some text content here", fontsize=12)
        # Add image
        img = Image.new("RGB", (100, 100), "red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        page.insert_image(fitz.Rect(50, 200, 150, 300), stream=buf.read())

        assert self.redactor._is_image_only_page(page) is False
        doc.close()


# ---------------------------------------------------------------------------
# _redact_ocr_page word matching tests (mocked OCR)
# ---------------------------------------------------------------------------

class TestRedactOcrPageMatching:
    """
    Test the word-matching logic in _redact_ocr_page by mocking
    pytesseract.image_to_data to return controlled OCR output.
    """

    def setup_method(self):
        self.redactor = PDFRedactor()

    def _mock_ocr_data(self, words_with_boxes):
        """
        Build a dict mimicking pytesseract.image_to_data(output_type=DICT).

        Args:
            words_with_boxes: List of (word_text, x, y, w, h) tuples.
        """
        data = {'text': [], 'left': [], 'top': [], 'width': [], 'height': [], 'conf': []}
        for word, x, y, w, h in words_with_boxes:
            data['text'].append(word)
            data['left'].append(x)
            data['top'].append(y)
            data['width'].append(w)
            data['height'].append(h)
            data['conf'].append(95)
        return data

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_single_word_exact_match(self, mock_ocr, mock_tess_ver):
        """Single-word PII 'Joe' matches OCR word 'Joe'."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("Joe", 100, 50, 80, 30),
            ("attended", 200, 50, 120, 30),
            ("school", 340, 50, 100, 30),
        ])

        page, doc = _make_image_only_page()
        items = [RedactionItem(page_num=1, text="Joe")]
        count = self.redactor._redact_ocr_page(page, items)
        assert count == 1
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_single_word_possessive_straight_apostrophe(self, mock_ocr, mock_tess_ver):
        """PII 'Joe' matches OCR word \"Joe's\" (straight apostrophe)."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("Joe's", 100, 50, 100, 30),
            ("behaviour", 220, 50, 140, 30),
        ])

        page, doc = _make_image_only_page()
        items = [RedactionItem(page_num=1, text="Joe")]
        count = self.redactor._redact_ocr_page(page, items)
        assert count == 1
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_single_word_possessive_curly_apostrophe(self, mock_ocr, mock_tess_ver):
        """PII 'Joe' matches OCR word 'Joe\u2019s' (curly apostrophe)."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("Joe\u2019s", 100, 50, 100, 30),
            ("report", 220, 50, 100, 30),
        ])

        page, doc = _make_image_only_page()
        items = [RedactionItem(page_num=1, text="Joe")]
        count = self.redactor._redact_ocr_page(page, items)
        assert count == 1
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_single_word_with_trailing_punctuation(self, mock_ocr, mock_tess_ver):
        """PII 'Joe' matches OCR word 'Joe,' (trailing comma)."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("Joe,", 100, 50, 90, 30),
            ("the", 210, 50, 50, 30),
            ("student", 280, 50, 110, 30),
        ])

        page, doc = _make_image_only_page()
        items = [RedactionItem(page_num=1, text="Joe")]
        count = self.redactor._redact_ocr_page(page, items)
        assert count == 1
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_multi_word_match(self, mock_ocr, mock_tess_ver):
        """Multi-word PII 'Joe Bloggs' matches consecutive OCR words."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("Report", 50, 50, 100, 30),
            ("for", 170, 50, 50, 30),
            ("Joe", 240, 50, 80, 30),
            ("Bloggs", 340, 50, 80, 30),
            ("dated", 440, 50, 90, 30),
        ])

        page, doc = _make_image_only_page()
        items = [RedactionItem(page_num=1, text="Joe Bloggs")]
        count = self.redactor._redact_ocr_page(page, items)
        assert count == 1
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_short_text_under_3_chars_skipped(self, mock_ocr, mock_tess_ver):
        """PII text shorter than 3 characters should be skipped."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("Jo", 100, 50, 40, 30),
            ("Smith", 160, 50, 90, 30),
        ])

        page, doc = _make_image_only_page()
        items = [RedactionItem(page_num=1, text="Jo")]
        count = self.redactor._redact_ocr_page(page, items)
        assert count == 0
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_no_match_returns_zero(self, mock_ocr, mock_tess_ver):
        """When PII text is not found in OCR output, return 0."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("The", 50, 50, 50, 30),
            ("student", 120, 50, 110, 30),
            ("attended", 250, 50, 120, 30),
        ])

        page, doc = _make_image_only_page()
        items = [RedactionItem(page_num=1, text="Joe")]
        count = self.redactor._redact_ocr_page(page, items)
        assert count == 0
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_case_insensitive_match(self, mock_ocr, mock_tess_ver):
        """Matching should be case-insensitive."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("JOE", 100, 50, 80, 30),
            ("BLOGGS", 200, 50, 80, 30),
        ])

        page, doc = _make_image_only_page()
        items = [RedactionItem(page_num=1, text="Joe Bloggs")]
        count = self.redactor._redact_ocr_page(page, items)
        assert count == 1
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_multiple_occurrences_all_redacted(self, mock_ocr, mock_tess_ver):
        """If 'Joe' appears twice, both should be redacted."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("Joe", 100, 50, 80, 30),
            ("attended", 200, 50, 120, 30),
            ("and", 340, 50, 50, 30),
            ("Joe", 410, 50, 80, 30),
            ("left", 510, 50, 60, 30),
        ])

        page, doc = _make_image_only_page()
        items = [RedactionItem(page_num=1, text="Joe")]
        count = self.redactor._redact_ocr_page(page, items)
        assert count == 2
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_multiple_pii_items(self, mock_ocr, mock_tess_ver):
        """Multiple PII items should each be matched independently."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("Joe", 100, 50, 80, 30),
            ("Bloggs", 200, 50, 80, 30),
            ("email:", 300, 50, 90, 30),
            ("joe@test.com", 410, 50, 200, 30),
        ])

        page, doc = _make_image_only_page()
        items = [
            RedactionItem(page_num=1, text="Joe"),
            RedactionItem(page_num=1, text="Bloggs"),
            RedactionItem(page_num=1, text="joe@test.com"),
        ]
        count = self.redactor._redact_ocr_page(page, items)
        assert count == 3
        doc.close()

    @patch('redactor.pytesseract')
    def test_no_tesseract_returns_zero(self, mock_tess):
        """When Tesseract is not available, should return 0 gracefully."""
        mock_tess.get_tesseract_version.side_effect = Exception("not installed")

        page, doc = _make_image_only_page()
        items = [RedactionItem(page_num=1, text="Joe")]
        count = self.redactor._redact_ocr_page(page, items)
        assert count == 0
        doc.close()


# ---------------------------------------------------------------------------
# redact_pdf routing tests
# ---------------------------------------------------------------------------

class TestRedactPdfRouting:
    """
    Verify that redact_pdf() routes image-only pages through _redact_ocr_page
    and text pages through the standard text-layer path.
    """

    def setup_method(self):
        self.redactor = PDFRedactor()

    @patch.object(PDFRedactor, '_redact_ocr_page', return_value=1)
    @patch.object(PDFRedactor, '_is_image_only_page', return_value=True)
    def test_image_only_page_uses_ocr_path(self, mock_is_img, mock_ocr_redact, tmp_path):
        """Image-only pages should be routed to _redact_ocr_page."""
        # Create a minimal PDF (doesn't matter what's in it — detection is mocked)
        doc = fitz.open()
        doc.new_page()
        input_pdf = tmp_path / "input.pdf"
        doc.save(str(input_pdf))
        doc.close()

        output_pdf = tmp_path / "output.pdf"
        items = [RedactionItem(page_num=1, text="Joe")]

        success, msg = self.redactor.redact_pdf(input_pdf, output_pdf, items)

        assert success is True
        mock_ocr_redact.assert_called_once()

    @patch.object(PDFRedactor, '_redact_text_search')
    @patch.object(PDFRedactor, '_is_image_only_page', return_value=False)
    def test_text_page_uses_standard_path(self, mock_is_img, mock_text_search, tmp_path):
        """Text pages should use standard _redact_text_search."""
        page, doc = _make_text_page("Joe attended school")
        input_pdf = tmp_path / "input.pdf"
        doc.save(str(input_pdf))
        doc.close()

        output_pdf = tmp_path / "output.pdf"
        items = [RedactionItem(page_num=1, text="Joe")]

        success, msg = self.redactor.redact_pdf(input_pdf, output_pdf, items)

        assert success is True
        mock_text_search.assert_called()

    @patch.object(PDFRedactor, '_redact_embedded_images', return_value=2)
    @patch.object(PDFRedactor, '_is_image_only_page', return_value=False)
    def test_embedded_images_scanned_on_text_pages(self, mock_is_img, mock_embed_redact, tmp_path):
        """Text pages should ALSO have embedded images scanned for PII."""
        page, doc = _make_text_page("Joe attended school")
        input_pdf = tmp_path / "input.pdf"
        doc.save(str(input_pdf))
        doc.close()

        output_pdf = tmp_path / "output.pdf"
        items = [RedactionItem(page_num=1, text="Joe")]

        success, msg = self.redactor.redact_pdf(input_pdf, output_pdf, items)

        assert success is True
        mock_embed_redact.assert_called_once()

    @patch.object(PDFRedactor, '_redact_embedded_images', return_value=0)
    @patch.object(PDFRedactor, '_redact_ocr_page', return_value=1)
    @patch.object(PDFRedactor, '_is_image_only_page', return_value=True)
    def test_embedded_images_scanned_on_ocr_pages_too(self, mock_is_img, mock_ocr, mock_embed_redact, tmp_path):
        """Image-only pages should ALSO run per-image scanning after OCR page redaction."""
        doc = fitz.open()
        doc.new_page()
        input_pdf = tmp_path / "input.pdf"
        doc.save(str(input_pdf))
        doc.close()

        output_pdf = tmp_path / "output.pdf"
        items = [RedactionItem(page_num=1, text="Joe")]

        success, msg = self.redactor.redact_pdf(input_pdf, output_pdf, items)

        assert success is True
        mock_embed_redact.assert_called_once()


# ---------------------------------------------------------------------------
# Service layer tests — OCR items not skipped
# ---------------------------------------------------------------------------

class TestServiceLayerOcrItems:
    """
    Verify that redaction_service.py no longer skips OCR page items
    from redaction or verification.
    """

    def test_ocr_items_included_in_verification(self):
        """
        When selected_matches include items on OCR pages,
        they should all be sent to verify_redaction_ocr — none filtered out.
        """
        # Import service layer
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'services'))
        from redaction_service import RedactionService, RedactionRequest

        # The key change: the old code filtered out OCR pages from verification:
        #   redacted_texts = [m.text for m in selected_matches if m.page_num not in ocr_pages]
        # The new code includes all:
        #   redacted_texts = [m.text for m in selected_matches]

        # We verify this by reading the source and checking the pattern
        service_path = Path(__file__).parent.parent / "src" / "services" / "redaction_service.py"
        source = service_path.read_text()

        # Should NOT contain the old filtering pattern
        assert "if m.page_num not in ocr_pages" not in source, \
            "Service layer still filters out OCR pages from verification"

        # Should contain the new all-inclusive pattern
        assert "redacted_texts = [m.text for m in selected_matches]" in source, \
            "Service layer should include all matches in verification"

    def test_ocr_warnings_not_flagged_in_audit_log(self):
        """
        OCR page items should produce an informational warning but NOT
        be flagged as errors in the audit log (no logger.add_flagged_file).
        """
        service_path = Path(__file__).parent.parent / "src" / "services" / "redaction_service.py"
        source = service_path.read_text()

        # The OCR warning block should NOT call logger.add_flagged_file
        # Find the OCR warning section
        ocr_section_start = source.find("# Note OCR pages")
        if ocr_section_start == -1:
            ocr_section_start = source.find("ocr_item_count")
        assert ocr_section_start != -1, "Could not find OCR handling section"

        # Get the section between "ocr_item_count" and the next major comment/section
        ocr_section = source[ocr_section_start:ocr_section_start + 800]

        assert "add_flagged_file" not in ocr_section, \
            "OCR warning should NOT flag files in audit log (items are now actually redacted)"

        assert "manual review recommended" in ocr_section, \
            "OCR warning should recommend manual review"


# ---------------------------------------------------------------------------
# _redact_embedded_images tests (per-image OCR scanning)
# ---------------------------------------------------------------------------

class TestRedactEmbeddedImages:
    """
    Test the per-image OCR scanning that extracts each embedded image,
    OCRs it independently, and blacks out PII matches in the image pixels.
    """

    def setup_method(self):
        self.redactor = PDFRedactor()

    def _mock_ocr_data(self, words_with_boxes):
        """Build pytesseract.image_to_data DICT output."""
        data = {'text': [], 'left': [], 'top': [], 'width': [], 'height': [], 'conf': []}
        for word, x, y, w, h in words_with_boxes:
            data['text'].append(word)
            data['left'].append(x)
            data['top'].append(y)
            data['width'].append(w)
            data['height'].append(h)
            data['conf'].append(95)
        return data

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_finds_pii_in_embedded_image(self, mock_ocr, mock_tess_ver):
        """PII found inside an embedded image should be redacted."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("Joe", 100, 50, 80, 30),
            ("Bloggs", 200, 50, 80, 30),
        ])

        page, doc = _make_hybrid_page()
        items = [RedactionItem(page_num=1, text="Joe Bloggs")]
        count = self.redactor._redact_embedded_images(page, items)
        assert count >= 1
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_no_pii_returns_zero(self, mock_ocr, mock_tess_ver):
        """When no PII is found in any image, return 0."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("The", 50, 50, 50, 30),
            ("report", 120, 50, 100, 30),
        ])

        page, doc = _make_hybrid_page()
        items = [RedactionItem(page_num=1, text="Joe")]
        count = self.redactor._redact_embedded_images(page, items)
        assert count == 0
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_page_with_no_images_returns_zero(self, mock_ocr, mock_tess_ver):
        """A text-only page (no images) should return 0 immediately."""
        mock_tess_ver.return_value = '5.0'

        page, doc = _make_text_page("Hello world")
        items = [RedactionItem(page_num=1, text="Hello")]
        count = self.redactor._redact_embedded_images(page, items)
        assert count == 0
        # OCR should never be called — no images to scan
        mock_ocr.assert_not_called()
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_multiple_images_all_scanned(self, mock_ocr, mock_tess_ver):
        """Each embedded image should be OCR-scanned independently."""
        mock_tess_ver.return_value = '5.0'
        # First image has PII, second doesn't
        mock_ocr.side_effect = [
            self._mock_ocr_data([("Joe", 10, 10, 50, 20)]),
            self._mock_ocr_data([("nothing", 10, 10, 80, 20)]),
        ]

        # Create page with TWO images
        doc = fitz.open()
        page = doc.new_page()
        for i in range(2):
            img = Image.new("RGB", (200, 200), "white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            y_off = i * 250
            page.insert_image(fitz.Rect(50, 50 + y_off, 250, 250 + y_off), stream=buf.read())

        items = [RedactionItem(page_num=1, text="Joe")]
        count = self.redactor._redact_embedded_images(page, items)
        assert count == 1
        assert mock_ocr.call_count == 2  # Both images scanned
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_email_address_in_image(self, mock_ocr, mock_tess_ver):
        """Email addresses in images should be matched (substring match for special chars)."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("fred.bloggs@emaildomain.com", 10, 10, 400, 20),
        ])

        page, doc = _make_hybrid_page()
        items = [RedactionItem(page_num=1, text="fred.bloggs@emaildomain.com")]
        count = self.redactor._redact_embedded_images(page, items)
        assert count >= 1
        doc.close()

    @patch('redactor.pytesseract')
    def test_no_tesseract_returns_zero(self, mock_tess):
        """Graceful degradation when Tesseract is not available."""
        mock_tess.get_tesseract_version.side_effect = Exception("not installed")

        page, doc = _make_hybrid_page()
        items = [RedactionItem(page_num=1, text="Joe")]
        count = self.redactor._redact_embedded_images(page, items)
        assert count == 0
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_image_replaced_in_pdf(self, mock_ocr, mock_tess_ver):
        """After redaction, the image in the PDF should be replaced (different bytes)."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("Joe", 100, 50, 80, 30),
        ])

        page, doc = _make_hybrid_page()

        # Get original image bytes
        images = page.get_images(full=True)
        assert len(images) >= 1
        orig_xref = images[0][0]
        orig_img_data = doc.extract_image(orig_xref)
        orig_bytes = orig_img_data['image']

        items = [RedactionItem(page_num=1, text="Joe")]
        count = self.redactor._redact_embedded_images(page, items)
        assert count >= 1

        # Image bytes should have changed (black rectangle drawn)
        new_img_data = doc.extract_image(orig_xref)
        new_bytes = new_img_data['image']
        assert new_bytes != orig_bytes
        doc.close()
