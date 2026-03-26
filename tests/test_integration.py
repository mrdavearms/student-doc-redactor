"""End-to-end integration tests for the full redaction pipeline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import fitz
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Service-layer imports use full paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.core.redactor import PDFRedactor, RedactionItem
from src.core.pii_detector import PIIDetector


def _make_test_pdf(tmp_path, pages_content):
    """Create a multi-page PDF with specified text content per page."""
    pdf_path = tmp_path / "test_input.pdf"
    doc = fitz.open()
    for page_text in pages_content:
        page = doc.new_page()
        page.insert_text((72, 72), page_text, fontsize=12)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _make_pdf_with_link(tmp_path, body_text, link_uri):
    """Create a PDF with a link annotation."""
    pdf_path = tmp_path / "test_link.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), body_text, fontsize=12)
    link = {"kind": fitz.LINK_URI, "from": fitz.Rect(72, 72, 200, 90), "uri": link_uri}
    page.insert_link(link)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _make_pdf_with_bookmark(tmp_path, body_text, bookmark_title):
    """Create a PDF with a bookmark/outline entry."""
    pdf_path = tmp_path / "test_bookmark.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), body_text, fontsize=12)
    doc.set_toc([[1, bookmark_title, 1]])
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestRedactorLinkCleanup:
    def setup_method(self):
        self.redactor = PDFRedactor()

    def test_link_with_pii_email_deleted(self, tmp_path):
        pdf = _make_pdf_with_link(tmp_path, "Contact us", "mailto:jane.smith@school.edu")
        out = tmp_path / "out.pdf"
        items = [RedactionItem(page_num=1, text="jane.smith@school.edu")]
        self.redactor.redact_pdf(pdf, out, items)
        doc = fitz.open(str(out))
        links = doc[0].get_links()
        pii_links = [l for l in links if "jane" in l.get("uri", "").lower()]
        assert len(pii_links) == 0
        doc.close()

    def test_link_without_pii_preserved(self, tmp_path):
        pdf = _make_pdf_with_link(tmp_path, "Visit website", "https://example.com")
        out = tmp_path / "out.pdf"
        items = [RedactionItem(page_num=1, text="Jane Smith")]
        self.redactor.redact_pdf(pdf, out, items)
        doc = fitz.open(str(out))
        links = doc[0].get_links()
        assert any("example.com" in l.get("uri", "") for l in links)
        doc.close()


class TestRedactorBookmarkCleanup:
    def setup_method(self):
        self.redactor = PDFRedactor()

    def test_bookmark_pii_replaced(self, tmp_path):
        pdf = _make_pdf_with_bookmark(tmp_path, "Report content", "Assessment for Jane Smith")
        out = tmp_path / "out.pdf"
        items = [RedactionItem(page_num=1, text="Jane Smith")]
        self.redactor.redact_pdf(pdf, out, items)
        doc = fitz.open(str(out))
        toc = doc.get_toc()
        for entry in toc:
            assert "jane" not in entry[1].lower()
            assert "smith" not in entry[1].lower()
        doc.close()


class TestRedactorMetadataHardening:
    def setup_method(self):
        self.redactor = PDFRedactor()

    def test_structure_tree_stripped(self, tmp_path):
        pdf_path = tmp_path / "tagged.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Jane Smith report", fontsize=12)
        doc.save(str(pdf_path))
        doc.close()
        out = tmp_path / "out.pdf"
        items = [RedactionItem(page_num=1, text="Jane Smith")]
        self.redactor.redact_pdf(pdf_path, out, items)
        doc = fitz.open(str(out))
        cat_xref = doc.pdf_catalog()
        st_type, _ = doc.xref_get_key(cat_xref, "StructTreeRoot")
        assert st_type == "null"
        doc.close()

    def test_names_dict_stripped(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Content", fontsize=12)
        doc.save(str(pdf_path))
        doc.close()
        out = tmp_path / "out.pdf"
        items = [RedactionItem(page_num=1, text="test")]
        self.redactor.redact_pdf(pdf_path, out, items)
        doc = fitz.open(str(out))
        cat_xref = doc.pdf_catalog()
        names_type, _ = doc.xref_get_key(cat_xref, "Names")
        assert names_type == "null"
        doc.close()


class TestMultiPageRedaction:
    def setup_method(self):
        self.redactor = PDFRedactor()

    def test_pii_on_multiple_pages_all_redacted(self, tmp_path):
        pdf = _make_test_pdf(tmp_path, [
            "Jane Smith attended the session.",
            "No PII on this page.",
            "Phone: 0412 345 678",
            "Contact Jane Smith for details.",
        ])
        out = tmp_path / "out.pdf"
        items = [
            RedactionItem(page_num=1, text="Jane Smith"),
            RedactionItem(page_num=3, text="0412 345 678"),
            RedactionItem(page_num=4, text="Jane Smith"),
        ]
        self.redactor.redact_pdf(pdf, out, items)
        doc = fitz.open(str(out))
        for page_num in [0, 2, 3]:  # 0-indexed
            text = doc[page_num].get_text().lower()
            assert "jane smith" not in text
        assert "0412 345 678" not in doc[2].get_text()
        doc.close()
