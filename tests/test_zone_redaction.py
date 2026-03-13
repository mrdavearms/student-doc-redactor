"""Tests for header/footer zone redaction (Stage 0)."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import fitz
import tempfile
from pathlib import Path
from redactor import PDFRedactor, RedactionItem

# Constants matching redactor.py
HEADER_ZONE_FRACTION = 0.12
FOOTER_ZONE_FRACTION = 0.08


def _create_pdf_with_text(text_positions):
    """
    Create a test PDF with text at specific vertical positions.

    Args:
        text_positions: list of (text, y_fraction) where y_fraction is 0.0 (top) to 1.0 (bottom)

    Returns:
        Path to temporary PDF
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4
    for text, y_frac in text_positions:
        y = page.rect.height * y_frac
        point = fitz.Point(50, y)
        page.insert_text(point, text, fontsize=12)

    tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    doc.save(tmp.name)
    doc.close()
    return Path(tmp.name)


class TestZoneRedaction:
    """Header/footer zone blanking."""

    def test_header_text_removed_when_enabled(self):
        """Text in top 12% of page should be gone after zone redaction."""
        pdf_path = _create_pdf_with_text([
            ("SCHOOL LETTERHEAD", 0.05),   # In header zone (5% from top)
            ("Main body text here", 0.50),  # In body (50%)
        ])
        output = Path(str(pdf_path).replace('.pdf', '_out.pdf'))

        redactor = PDFRedactor()
        success, msg = redactor.redact_pdf(pdf_path, output, [], redact_header_footer=True)

        assert success
        doc = fitz.open(str(output))
        page = doc[0]
        text = page.get_text()
        assert "SCHOOL LETTERHEAD" not in text
        assert "Main body text" in text
        doc.close()

        os.unlink(str(pdf_path))
        os.unlink(str(output))

    def test_footer_text_removed_when_enabled(self):
        """Text in bottom 8% of page should be gone after zone redaction."""
        pdf_path = _create_pdf_with_text([
            ("Main body text here", 0.50),
            ("123 School St, Sydney NSW 2000", 0.96),  # In footer zone
        ])
        output = Path(str(pdf_path).replace('.pdf', '_out.pdf'))

        redactor = PDFRedactor()
        success, msg = redactor.redact_pdf(pdf_path, output, [], redact_header_footer=True)

        assert success
        doc = fitz.open(str(output))
        page = doc[0]
        text = page.get_text()
        assert "123 School St" not in text
        assert "Main body text" in text
        doc.close()

        os.unlink(str(pdf_path))
        os.unlink(str(output))

    def test_zones_not_redacted_when_disabled(self):
        """When redact_header_footer=False, header/footer text should survive."""
        pdf_path = _create_pdf_with_text([
            ("SCHOOL LETTERHEAD", 0.05),
            ("Main body text here", 0.50),
        ])
        output = Path(str(pdf_path).replace('.pdf', '_out.pdf'))

        redactor = PDFRedactor()
        success, msg = redactor.redact_pdf(pdf_path, output, [], redact_header_footer=False)

        assert success
        doc = fitz.open(str(output))
        page = doc[0]
        text = page.get_text()
        assert "SCHOOL LETTERHEAD" in text
        doc.close()

        os.unlink(str(pdf_path))
        os.unlink(str(output))

    def test_zone_redaction_default_is_false(self):
        """Default behaviour should NOT redact zones (backwards compatible)."""
        pdf_path = _create_pdf_with_text([
            ("SCHOOL LETTERHEAD", 0.05),
            ("Main body text here", 0.50),
        ])
        output = Path(str(pdf_path).replace('.pdf', '_out.pdf'))

        redactor = PDFRedactor()
        # No redact_header_footer param — should default to False
        success, msg = redactor.redact_pdf(pdf_path, output, [])

        assert success
        doc = fitz.open(str(output))
        page = doc[0]
        text = page.get_text()
        assert "SCHOOL LETTERHEAD" in text
        doc.close()

        os.unlink(str(pdf_path))
        os.unlink(str(output))

    def test_zone_redaction_runs_on_all_pages(self):
        """Zone redaction should apply to EVERY page, not just pages with PII."""
        doc = fitz.open()
        for i in range(3):
            page = doc.new_page(width=595, height=842)
            page.insert_text(fitz.Point(50, 42), f"HEADER PAGE {i+1}", fontsize=12)
            page.insert_text(fitz.Point(50, 421), f"Body page {i+1}", fontsize=12)

        tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        doc.save(tmp.name)
        doc.close()
        pdf_path = Path(tmp.name)
        output = Path(str(pdf_path).replace('.pdf', '_out.pdf'))

        redactor = PDFRedactor()
        success, msg = redactor.redact_pdf(pdf_path, output, [], redact_header_footer=True)

        assert success
        doc = fitz.open(str(output))
        for i in range(3):
            text = doc[i].get_text()
            assert f"HEADER PAGE {i+1}" not in text
            assert f"Body page {i+1}" in text
        doc.close()

        os.unlink(str(pdf_path))
        os.unlink(str(output))
