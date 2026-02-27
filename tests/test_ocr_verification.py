import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import fitz
import pytest
from pathlib import Path
from redactor import PDFRedactor, RedactionItem
import tempfile


def _create_pdf_with_text(path, text="Hello World", font_size=14):
    """Create a simple PDF with known text."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=font_size)
    doc.save(str(path))
    doc.close()


def _tesseract_available():
    """Check if Tesseract OCR is available on this system."""
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


needs_tesseract = pytest.mark.skipif(
    not _tesseract_available(),
    reason="Tesseract OCR not installed"
)


class TestOCRVerification:

    @needs_tesseract
    def test_clean_redaction_passes_ocr_check(self):
        """After redacting text, OCR should not find it."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            out = Path(tmp) / "output.pdf"
            _create_pdf_with_text(src, "Jane Smith is a student")

            redactor = PDFRedactor()
            items = [RedactionItem(page_num=1, text="Jane Smith")]
            success, _ = redactor.redact_pdf(src, out, items)
            assert success

            all_clean, failures = redactor.verify_redaction_ocr(out, ["Jane Smith"])
            assert all_clean, f"OCR found redacted text: {failures}"

    @needs_tesseract
    def test_unredacted_text_fails_ocr_check(self):
        """Text that was NOT redacted should be found by OCR."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            _create_pdf_with_text(src, "Jane Smith is a student")

            redactor = PDFRedactor()
            all_clean, failures = redactor.verify_redaction_ocr(src, ["Jane Smith"])
            assert not all_clean
            assert len(failures) > 0

    @needs_tesseract
    def test_short_strings_skipped_in_ocr_check(self):
        """Strings shorter than 3 characters should be skipped to avoid false positives."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            _create_pdf_with_text(src, "JS is here")

            redactor = PDFRedactor()
            # "JS" is only 2 chars — should be skipped by OCR verification
            all_clean, failures = redactor.verify_redaction_ocr(src, ["JS"])
            assert all_clean, "Short strings (< 3 chars) should be skipped"

    @needs_tesseract
    def test_multiple_redacted_texts_all_verified(self):
        """OCR verification checks all provided texts."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            out = Path(tmp) / "output.pdf"

            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "Jane Smith", fontsize=14)
            page.insert_text((72, 120), "0412 345 678", fontsize=14)
            doc.save(str(src))
            doc.close()

            redactor = PDFRedactor()
            items = [
                RedactionItem(page_num=1, text="Jane Smith"),
                RedactionItem(page_num=1, text="0412 345 678"),
            ]
            success, _ = redactor.redact_pdf(src, out, items)
            assert success

            all_clean, failures = redactor.verify_redaction_ocr(
                out, ["Jane Smith", "0412 345 678"]
            )
            assert all_clean, f"OCR found redacted text: {failures}"

    @needs_tesseract
    def test_partial_redaction_reports_remaining_text(self):
        """If only some text is redacted, OCR should report the unredacted ones."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            out = Path(tmp) / "output.pdf"

            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "Jane Smith", fontsize=14)
            page.insert_text((72, 120), "Bob Jones", fontsize=14)
            doc.save(str(src))
            doc.close()

            redactor = PDFRedactor()
            # Only redact Jane Smith, NOT Bob Jones
            items = [RedactionItem(page_num=1, text="Jane Smith")]
            success, _ = redactor.redact_pdf(src, out, items)
            assert success

            all_clean, failures = redactor.verify_redaction_ocr(
                out, ["Jane Smith", "Bob Jones"]
            )
            assert not all_clean
            # Bob Jones should be in the failures
            assert any("Bob Jones" in f for f in failures)

    @needs_tesseract
    def test_multi_page_pdf_verified(self):
        """OCR verification works across multiple pages."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            out = Path(tmp) / "output.pdf"

            doc = fitz.open()
            page1 = doc.new_page()
            page1.insert_text((72, 72), "Jane Smith on page one", fontsize=14)
            page2 = doc.new_page()
            page2.insert_text((72, 72), "Jane Smith on page two", fontsize=14)
            doc.save(str(src))
            doc.close()

            redactor = PDFRedactor()
            items = [
                RedactionItem(page_num=1, text="Jane Smith"),
                RedactionItem(page_num=2, text="Jane Smith"),
            ]
            success, _ = redactor.redact_pdf(src, out, items)
            assert success

            all_clean, failures = redactor.verify_redaction_ocr(out, ["Jane Smith"])
            assert all_clean, f"OCR found redacted text: {failures}"

    def test_ocr_verification_handles_missing_tesseract_gracefully(self):
        """If Tesseract is not installed, the method should return an error, not crash."""
        # This test always runs — it tests the error handling path
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            _create_pdf_with_text(src, "Hello World")

            redactor = PDFRedactor()
            # Even if Tesseract is available, this validates the method signature
            all_clean, failures = redactor.verify_redaction_ocr(src, ["Hello World"])
            # Result depends on Tesseract availability, but should not crash
            assert isinstance(all_clean, bool)
            assert isinstance(failures, list)
