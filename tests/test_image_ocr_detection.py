"""
Images embedded in pages that also have a text layer are OCR'd for detection.

A screenshot of an email pasted into a report carries names, phone numbers
and email addresses the text layer never sees. Until this change nothing was
offered for them, so redaction Stage 2 (which only blacks out SELECTED items)
never touched them. The OCR text is kept separate from the page's own text:
detection reads both, the de-identified output is rebuilt from the page's own
text and must not pick up position-less OCR noise.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import io
from pathlib import Path
from unittest.mock import patch

import fitz
import pytest
from PIL import Image, ImageDraw, ImageFont

from text_extractor import TextExtractor
from redactor import PDFRedactor, RedactionItem
from src.services.detection_service import DetectionService


BODY = ("Billy Bob has made steady progress this semester in literacy and numeracy. "
        "He works well in small groups and responds to clear routines.")


def _png(lines, font_size=34):
    font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', font_size) \
        if os.path.exists('/System/Library/Fonts/Supplemental/Arial.ttf') else ImageFont.load_default()
    img = Image.new('RGB', (1000, 30 + 55 * len(lines)), 'white')
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((20, 15 + 55 * i), line, fill='black', font=font)
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


def _pdf_with_image(path: Path, pages: int = 1, image: bytes | None = None,
                    reuse_xref: bool = True):
    doc = fitz.open()
    xref = None
    for _ in range(pages):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(72, 72, 540, 200), BODY, fontsize=11)
        if image is not None:
            if xref is not None and reuse_xref:
                page.insert_image(fitz.Rect(72, 300, 540, 420), xref=xref)
            else:
                xref = page.insert_image(fitz.Rect(72, 300, 540, 420), stream=image)
    doc.save(str(path))
    doc.close()


def _ocr_data(words):
    """pytesseract.image_to_data(output_type=DICT) shape, one line."""
    n = len(words)
    return {
        'text': list(words), 'conf': [95] * n,
        'block_num': [1] * n, 'line_num': [1] * n,
        'left': [0] * n, 'top': [0] * n, 'width': [10] * n, 'height': [10] * n,
    }


class TestExtractorMocked:

    def _extractor(self):
        ex = TextExtractor()
        ex.tesseract_available = True
        return ex

    @patch('text_extractor.pytesseract.image_to_data')
    def test_image_text_is_reported_separately_from_the_page_text(self, mock_ocr, tmp_path):
        mock_ocr.return_value = _ocr_data(["Priya", "Raman", "0412", "345", "678"])
        pdf = tmp_path / "report.pdf"
        _pdf_with_image(pdf, image=_png(["x"]))

        page = self._extractor().extract_text_from_pdf(pdf)['pages'][1]
        assert page['method'] == 'native'
        assert page['image_text'] == "Priya Raman 0412 345 678"
        assert "Priya" not in page['text']

    @patch('text_extractor.pytesseract.image_to_data')
    def test_one_image_on_every_page_is_ocrd_once_per_document(self, mock_ocr, tmp_path):
        mock_ocr.return_value = _ocr_data(["Riverside", "Primary"])
        pdf = tmp_path / "report.pdf"
        _pdf_with_image(pdf, pages=3, image=_png(["x"]), reuse_xref=True)

        ex = self._extractor()
        result = ex.extract_text_from_pdf(pdf)
        assert [result['pages'][n]['image_text'] for n in (1, 2, 3)] == ["Riverside Primary"] * 3
        assert mock_ocr.call_count == 1
        # The cache is per document, not per extractor.
        ex.extract_text_from_pdf(pdf)
        assert mock_ocr.call_count == 2

    @patch('text_extractor.pytesseract.image_to_data')
    def test_page_without_images_does_not_call_ocr(self, mock_ocr, tmp_path):
        pdf = tmp_path / "report.pdf"
        _pdf_with_image(pdf, image=None)
        page = self._extractor().extract_text_from_pdf(pdf)['pages'][1]
        assert page['image_text'] == ""
        mock_ocr.assert_not_called()

    @patch('text_extractor.pytesseract.image_to_data')
    def test_no_tesseract_means_no_image_text(self, mock_ocr, tmp_path):
        pdf = tmp_path / "report.pdf"
        _pdf_with_image(pdf, image=_png(["x"]))
        ex = TextExtractor()
        ex.tesseract_available = False
        assert ex.extract_text_from_pdf(pdf)['pages'][1]['image_text'] == ""
        mock_ocr.assert_not_called()


class TestDetectionReadsImageText:

    @patch('text_extractor.pytesseract.image_to_data')
    def test_phone_number_inside_a_screenshot_is_detected(self, mock_ocr, tmp_path):
        mock_ocr.return_value = _ocr_data(["Phone:", "0412", "345", "678"])
        pdf = tmp_path / "report.pdf"
        _pdf_with_image(pdf, image=_png(["x"]))

        service = DetectionService(student_name="Billy Bob")
        service._extractor.tesseract_available = True
        matches = service.detect_all([pdf]).pii_by_document[pdf].matches
        phones = [m for m in matches if m.category == "Phone number"]
        assert [m.text for m in phones] == ["0412 345 678"]
        assert phones[0].page_num == 1


def _tesseract_available():
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _tesseract_available(), reason="Tesseract not installed")
class TestEndToEndWithRealTesseract:

    def test_name_and_phone_in_a_pasted_screenshot_are_found_and_redacted(self, tmp_path):
        pdf = tmp_path / "report.pdf"
        _pdf_with_image(pdf, image=_png(["From: Priya Raman", "Phone: 0412 345 678"]))

        # Regex-only detection so the test does not depend on spaCy: the
        # teacher is entered as a parent name, the phone is structured PII.
        service = DetectionService(student_name="Billy Bob", parent_names=["Priya Raman"])
        matches = service.detect_all([pdf]).pii_by_document[pdf].matches
        texts = {m.text for m in matches}
        assert "Priya Raman" in texts
        assert "0412 345 678" in texts

        out = tmp_path / "report_redacted.pdf"
        items = [RedactionItem(page_num=m.page_num, text=m.text, bbox=m.bbox) for m in matches]
        redactor = PDFRedactor()
        ok, message = redactor.redact_pdf(pdf, out, items)
        assert ok, message
        clean, leftovers = redactor.verify_redaction_ocr(out, ["Priya Raman", "0412 345 678", "Raman"])
        assert clean, leftovers
