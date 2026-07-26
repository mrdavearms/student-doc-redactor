"""
Single-document redaction path: preparing one file instead of a folder, and
saving the result under a user-chosen filename (the Save As dialog).
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from src.services.conversion_service import ConversionService
from src.services.redaction_service import RedactionService, RedactionRequest

client = TestClient(app)


def _make_pdf(path: Path, text: str = "Joe Bloggs attended.") -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


# ── ConversionService.process_file ───────────────────────────────────────

class TestProcessSingleFile:
    def test_pdf_is_listed_as_processable(self, tmp_path):
        pdf = _make_pdf(tmp_path / "report.pdf")
        results = ConversionService().process_file(pdf)

        assert results.pdf_files == [pdf]
        assert results.processable_count == 1
        assert results.flagged_count == 0

    def test_does_not_pick_up_the_other_files_in_the_folder(self, tmp_path):
        """The whole point of single-document mode — siblings stay untouched."""
        pdf = _make_pdf(tmp_path / "chosen.pdf")
        _make_pdf(tmp_path / "sibling.pdf")

        results = ConversionService().process_file(pdf)

        assert results.all_processable_pdfs == [pdf]

    def test_unsupported_type_is_flagged_not_crashed(self, tmp_path):
        odd = tmp_path / "notes.txt"
        odd.write_text("hello")

        results = ConversionService().process_file(odd)

        assert results.processable_count == 0
        assert results.flagged_count == 1
        flagged_path, reason = results.failed_conversions[0]
        assert flagged_path == odd
        assert "Unsupported file type" in reason

    def test_password_protected_pdf_is_flagged(self, tmp_path):
        pdf = tmp_path / "locked.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.save(str(pdf), encryption=fitz.PDF_ENCRYPT_AES_256,
                 owner_pw="owner", user_pw="user")
        doc.close()

        results = ConversionService().process_file(pdf)

        assert results.password_protected == [pdf]
        assert results.processable_count == 0


# ── API endpoints ─────────────────────────────────────────────────────────

class TestFileEndpoints:
    def test_process_endpoint_returns_the_single_pdf(self, tmp_path):
        pdf = _make_pdf(tmp_path / "report.pdf")

        resp = client.post("/api/file/process", json={"file_path": str(pdf)})

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["pdf_files"] == [str(pdf)]
        assert body["processable_count"] == 1

    def test_process_endpoint_400s_on_missing_file(self):
        resp = client.post("/api/file/process", json={"file_path": "/no/such/file.pdf"})
        assert resp.status_code == 400
        assert "File not found" in resp.json()["detail"]

    def test_process_endpoint_400s_when_given_a_folder(self, tmp_path):
        resp = client.post("/api/file/process", json={"file_path": str(tmp_path)})
        assert resp.status_code == 400

    def test_validate_reports_a_usable_document(self, tmp_path):
        pdf = _make_pdf(tmp_path / "report.pdf")
        body = client.post("/api/file/validate", json={"file_path": str(pdf)}).json()
        assert body == {"exists": True, "is_file": True, "supported": True,
                        "path": str(pdf)}

    def test_validate_reports_unsupported_type_separately(self, tmp_path):
        odd = tmp_path / "notes.txt"
        odd.write_text("hello")
        body = client.post("/api/file/validate", json={"file_path": str(odd)}).json()
        assert body["exists"] is True
        assert body["supported"] is False

    def test_validate_reports_missing_file(self):
        body = client.post("/api/file/validate",
                           json={"file_path": "/no/such/file.pdf"}).json()
        assert body["exists"] is False
        assert body["is_file"] is False


# ── User-chosen output filename (Save As) ────────────────────────────────

class TestCustomOutputFilename:
    def _request(self, tmp_path, docs, **kwargs) -> RedactionRequest:
        detected = {d: {"matches": [], "text_data": {"pages": {}, "ocr_pages": []}}
                    for d in docs}
        return RedactionRequest(
            folder_path=tmp_path,
            student_name="Joe Bloggs",
            documents=docs,
            detected_pii=detected,
            user_selections={},
            **kwargs,
        )

    def test_single_document_uses_the_chosen_name(self, tmp_path):
        pdf = _make_pdf(tmp_path / "Joe Bloggs Report.pdf")
        out = tmp_path / "output"

        results = RedactionService().execute(self._request(
            tmp_path, [pdf],
            custom_output_path=out,
            custom_output_filename="Term 3 assessment.pdf",
        ))

        assert results.document_results[0].output_path == out / "Term 3 assessment.pdf"
        assert (out / "Term 3 assessment.pdf").exists()

    def test_missing_extension_is_added(self, tmp_path):
        pdf = _make_pdf(tmp_path / "report.pdf")
        out = tmp_path / "output"

        results = RedactionService().execute(self._request(
            tmp_path, [pdf],
            custom_output_path=out,
            custom_output_filename="assessment",
        ))

        assert results.document_results[0].output_path.name == "assessment.pdf"

    @pytest.mark.parametrize("crafted", [
        "../escaped.pdf",
        "/etc/escaped.pdf",
        "..\\..\\escaped.pdf",
        "sub/dir/escaped.pdf",
    ])
    def test_directory_components_cannot_escape_the_output_folder(self, tmp_path, crafted):
        pdf = _make_pdf(tmp_path / "report.pdf")
        out = tmp_path / "output"

        results = RedactionService().execute(self._request(
            tmp_path, [pdf],
            custom_output_path=out,
            custom_output_filename=crafted,
        ))

        written = results.document_results[0].output_path
        assert written.parent == out
        assert written.name == "escaped.pdf"

    def test_ignored_when_several_documents_would_collide_on_it(self, tmp_path):
        docs = [_make_pdf(tmp_path / "Report One.pdf"),
                _make_pdf(tmp_path / "Report Two.pdf")]
        out = tmp_path / "output"

        results = RedactionService().execute(self._request(
            tmp_path, docs,
            custom_output_path=out,
            custom_output_filename="only-one-name.pdf",
        ))

        names = {r.output_path.name for r in results.document_results}
        assert names == {"Report One_redacted.pdf", "Report Two_redacted.pdf"}

    def test_default_naming_still_applies_without_an_override(self, tmp_path):
        pdf = _make_pdf(tmp_path / "Joe Bloggs Report.pdf")

        results = RedactionService().execute(self._request(tmp_path, [pdf]))

        # PII stripped from the filename, as before
        assert results.document_results[0].output_path.name == "Report_redacted.pdf"
