import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import fitz
from pathlib import Path
from redactor import PDFRedactor, RedactionItem
import tempfile


def _create_pdf_with_widgets(path, fields: dict):
    """
    Create a test PDF with form widgets containing the given field values.

    Args:
        path: Where to save the PDF.
        fields: Mapping of field_name → field_value.
    """
    doc = fitz.open()
    page = doc.new_page()

    # Add some regular content-stream text
    page.insert_text((72, 72), "Assessment Report", fontsize=14)

    # Add form widgets with values
    y = 150
    for name, value in fields.items():
        widget = fitz.Widget()
        widget.field_name = name
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.rect = fitz.Rect(72, y, 300, y + 20)
        widget.field_value = value
        page.add_widget(widget)
        y += 30

    doc.save(str(path))
    doc.close()


class TestWidgetRedaction:
    """Tests that PII in form widget field values is removed during redaction."""

    def test_widget_value_removed_after_redaction(self):
        """Widget containing PII text should be deleted after redaction."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            out = Path(tmp) / "output.pdf"
            _create_pdf_with_widgets(src, {"StudentName": "JOE BLOGGS"})

            redactor = PDFRedactor()
            items = [RedactionItem(page_num=1, text="JOE BLOGGS")]
            success, msg = redactor.redact_pdf(src, out, items)

            assert success, msg
            doc = fitz.open(str(out))
            page = doc[0]

            # Widget should be gone
            widget_values = [w.field_value for w in page.widgets() if w.field_value]
            assert "JOE BLOGGS" not in widget_values, (
                f"Widget still contains PII after redaction: {widget_values}"
            )

            # search_for should find nothing
            assert len(page.search_for("JOE BLOGGS")) == 0
            doc.close()

    def test_non_pii_widgets_preserved(self):
        """Widgets that don't contain redacted PII should remain untouched."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            out = Path(tmp) / "output.pdf"
            _create_pdf_with_widgets(src, {
                "StudentName": "JOE BLOGGS",
                "Score": "85",
                "Level": "Average",
            })

            redactor = PDFRedactor()
            items = [RedactionItem(page_num=1, text="JOE BLOGGS")]
            success, msg = redactor.redact_pdf(src, out, items)

            assert success, msg
            doc = fitz.open(str(out))
            page = doc[0]

            remaining = {w.field_name: w.field_value for w in page.widgets()}
            assert "StudentName" not in remaining, "PII widget should be deleted"
            assert remaining.get("Score") == "85", "Non-PII widget should be preserved"
            assert remaining.get("Level") == "Average", "Non-PII widget should be preserved"
            doc.close()

    def test_partial_match_deletes_widget(self):
        """Widget is deleted if any redacted PII text appears in its value."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            out = Path(tmp) / "output.pdf"
            _create_pdf_with_widgets(src, {
                "FullName": "Assessment for JOE BLOGGS - Year 6",
            })

            redactor = PDFRedactor()
            items = [RedactionItem(page_num=1, text="JOE BLOGGS")]
            success, msg = redactor.redact_pdf(src, out, items)

            assert success, msg
            doc = fitz.open(str(out))
            page = doc[0]

            widget_values = [w.field_value for w in page.widgets() if w.field_value]
            for val in widget_values:
                assert "JOE BLOGGS" not in val.upper(), (
                    f"Widget still contains PII: {val}"
                )
            doc.close()

    def test_multiple_pii_widgets_all_deleted(self):
        """All widgets containing any redacted PII should be deleted."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            out = Path(tmp) / "output.pdf"
            _create_pdf_with_widgets(src, {
                "Student": "JOE BLOGGS",
                "Informant": "Jane Holmes",
                "Examiner1": "Angela Rogers",
                "Examiner2": "Angela Rogers",
                "Score": "72",
            })

            redactor = PDFRedactor()
            items = [
                RedactionItem(page_num=1, text="JOE BLOGGS"),
                RedactionItem(page_num=1, text="Jane Holmes"),
                RedactionItem(page_num=1, text="Angela Rogers"),
            ]
            success, msg = redactor.redact_pdf(src, out, items)

            assert success, msg
            doc = fitz.open(str(out))
            page = doc[0]

            remaining = {w.field_name: w.field_value for w in page.widgets()}
            assert "Student" not in remaining
            assert "Informant" not in remaining
            assert "Examiner1" not in remaining
            assert "Examiner2" not in remaining
            assert remaining.get("Score") == "72"
            doc.close()

    def test_verify_redaction_checks_widget_values(self):
        """verify_redaction should catch PII surviving in widget field values."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            _create_pdf_with_widgets(src, {"StudentName": "JOE BLOGGS"})

            redactor = PDFRedactor()

            # Without our fix, widget value would survive — verify should catch it
            is_clean, msg = redactor.verify_redaction(src, "JOE BLOGGS")
            assert not is_clean, "verify_redaction should detect PII in widget values"

    def test_no_widgets_page_no_error(self):
        """Redacting a page with no widgets should not raise errors."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.pdf"
            out = Path(tmp) / "output.pdf"

            # Create a plain PDF with no widgets
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "Hello World", fontsize=14)
            doc.save(str(src))
            doc.close()

            redactor = PDFRedactor()
            items = [RedactionItem(page_num=1, text="Hello")]
            success, msg = redactor.redact_pdf(src, out, items)
            assert success, msg
