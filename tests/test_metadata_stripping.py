import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import fitz
from pathlib import Path
from redactor import PDFRedactor, RedactionItem
import tempfile


def _create_pdf_with_metadata(path, metadata=None, embed_file=False):
    """Create a test PDF with known metadata and optionally an embedded file."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello World", fontsize=14)

    if metadata:
        doc.set_metadata(metadata)

    if embed_file:
        doc.embfile_add("test_embed.txt", b"embedded content", filename="test_embed.txt")

    doc.save(str(path))
    doc.close()


class TestMetadataStripping:

    def test_author_cleared_after_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            out = Path(tmp) / "output.pdf"
            _create_pdf_with_metadata(src, {"author": "Secret Author"})

            redactor = PDFRedactor()
            items = [RedactionItem(page_num=1, text="Hello")]
            success, _ = redactor.redact_pdf(src, out, items)

            assert success
            doc = fitz.open(str(out))
            meta = doc.metadata
            assert meta.get("author", "") == ""
            doc.close()

    def test_title_cleared_after_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            out = Path(tmp) / "output.pdf"
            _create_pdf_with_metadata(src, {"title": "Confidential Report"})

            redactor = PDFRedactor()
            items = [RedactionItem(page_num=1, text="Hello")]
            success, _ = redactor.redact_pdf(src, out, items)

            assert success
            doc = fitz.open(str(out))
            assert doc.metadata.get("title", "") == ""
            doc.close()

    def test_creator_and_producer_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            out = Path(tmp) / "output.pdf"
            _create_pdf_with_metadata(src, {
                "creator": "My App v1.0",
                "producer": "LibreOffice 7.5"
            })

            redactor = PDFRedactor()
            items = [RedactionItem(page_num=1, text="Hello")]
            success, _ = redactor.redact_pdf(src, out, items)

            assert success
            doc = fitz.open(str(out))
            assert doc.metadata.get("creator", "") == ""
            assert doc.metadata.get("producer", "") == ""
            doc.close()

    def test_dates_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            out = Path(tmp) / "output.pdf"
            _create_pdf_with_metadata(src, {
                "creationDate": "D:20240101120000",
                "modDate": "D:20240601120000"
            })

            redactor = PDFRedactor()
            items = [RedactionItem(page_num=1, text="Hello")]
            success, _ = redactor.redact_pdf(src, out, items)

            assert success
            doc = fitz.open(str(out))
            assert doc.metadata.get("creationDate", "") == ""
            assert doc.metadata.get("modDate", "") == ""
            doc.close()

    def test_all_metadata_fields_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            out = Path(tmp) / "output.pdf"
            _create_pdf_with_metadata(src, {
                "author": "Author",
                "title": "Title",
                "subject": "Subject",
                "creator": "Creator",
                "producer": "Producer",
                "keywords": "keyword1, keyword2",
                "creationDate": "D:20240101120000",
                "modDate": "D:20240601120000",
            })

            redactor = PDFRedactor()
            items = [RedactionItem(page_num=1, text="Hello")]
            success, _ = redactor.redact_pdf(src, out, items)

            assert success
            doc = fitz.open(str(out))
            meta = doc.metadata
            for key in ["author", "title", "subject", "creator", "producer",
                        "keywords", "creationDate", "modDate"]:
                assert meta.get(key, "") == "", f"Metadata field '{key}' not cleared"
            doc.close()

    def test_xmp_metadata_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            out = Path(tmp) / "output.pdf"

            # Create PDF and add XMP metadata
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "Hello World")
            xmp = '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta><rdf:RDF><rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Secret Title</dc:title></rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
            doc.set_xml_metadata(xmp)
            doc.save(str(src))
            doc.close()

            redactor = PDFRedactor()
            items = [RedactionItem(page_num=1, text="Hello")]
            success, _ = redactor.redact_pdf(src, out, items)

            assert success
            doc = fitz.open(str(out))
            xml = doc.get_xml_metadata()
            # XMP should be empty or not contain the secret title
            assert "Secret Title" not in (xml or "")
            doc.close()

    def test_embedded_files_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            out = Path(tmp) / "output.pdf"
            _create_pdf_with_metadata(src, embed_file=True)

            # Verify embedded file exists in source
            doc = fitz.open(str(src))
            assert doc.embfile_count() > 0
            doc.close()

            redactor = PDFRedactor()
            items = [RedactionItem(page_num=1, text="Hello")]
            success, _ = redactor.redact_pdf(src, out, items)

            assert success
            doc = fitz.open(str(out))
            assert doc.embfile_count() == 0
            doc.close()

    def test_redaction_still_works_with_metadata_stripping(self):
        """Ensure the actual text redaction still works alongside metadata stripping."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            out = Path(tmp) / "output.pdf"
            _create_pdf_with_metadata(src, {"author": "Secret Author"})

            redactor = PDFRedactor()
            items = [RedactionItem(page_num=1, text="Hello World")]
            success, _ = redactor.redact_pdf(src, out, items)

            assert success
            # Verify text is gone
            doc = fitz.open(str(out))
            text = doc[0].get_text()
            assert "Hello World" not in text
            # Verify metadata is gone
            assert doc.metadata.get("author", "") == ""
            doc.close()
