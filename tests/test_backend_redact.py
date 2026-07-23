import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import tempfile
from pathlib import Path

import fitz
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def _make_pdf(path, text):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=12)
    doc.save(str(path))
    doc.close()


def test_redact_honours_only_selected_keys():
    """detect → redact must redact ONLY the matches whose keys are in selected_keys."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Student Joe Bloggs and parent Mary Bloggs attended.")

        det = client.post("/api/pii/detect", json={
            "pdf_paths": [str(pdf)],
            "student_name": "Joe Bloggs",
            "parent_names": ["Mary Bloggs"],
            "family_names": [],
            "organisation_names": [],
        })
        assert det.status_code == 200, det.text
        doc0 = det.json()["documents"][0]
        matches = doc0["matches"]
        assert len(matches) >= 1, "expected at least one detected match"

        selected = [f"{pdf}_0"]
        red = client.post("/api/redact", json={
            "folder_path": tmp,
            "student_name": "Joe Bloggs",
            "parent_names": ["Mary Bloggs"],
            "family_names": [],
            "organisation_names": [],
            "redact_header_footer": False,
            "documents": [str(pdf)],
            "detected_pii": {},
            "selected_keys": selected,
            "folder_action": "overwrite",
        })
        assert red.status_code == 200, red.text
        body = red.json()
        assert body["document_results"][0]["items_redacted"] == 1


from unittest.mock import patch


def test_detect_internal_error_returns_clean_500():
    """An unexpected service error must become a 500 with a string detail,
    not an unhandled raw traceback."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Joe Bloggs")

        with patch("backend.main.DetectionService") as MockSvc:
            MockSvc.return_value.detect_all.side_effect = RuntimeError("spaCy exploded")
            resp = client.post("/api/pii/detect", json={
                "pdf_paths": [str(pdf)],
                "student_name": "Joe Bloggs",
                "parent_names": [],
                "family_names": [],
                "organisation_names": [],
            })
    assert resp.status_code == 500
    detail = resp.json().get("detail", "")
    assert isinstance(detail, str) and len(detail) > 0
    assert "Detection failed" in detail


def test_detect_bad_path_still_returns_400():
    """A genuine client error (missing file) must remain a 400, not become a 500."""
    resp = client.post("/api/pii/detect", json={
        "pdf_paths": ["/no/such/file.pdf"],
        "student_name": "Joe Bloggs",
        "parent_names": [],
        "family_names": [],
        "organisation_names": [],
    })
    assert resp.status_code == 400


class TestRedactionCancel:
    def _make_request(self, tmp_path, names):
        import fitz
        from src.services.redaction_service import RedactionRequest

        docs = []
        for name in names:
            p = tmp_path / name
            d = fitz.open()
            pg = d.new_page()
            pg.insert_text((72, 72), f"Document {name}")
            d.save(str(p))
            d.close()
            docs.append(p)

        detected = {p: {"matches": [], "text_data": {"pages": {}, "ocr_pages": []}}
                    for p in docs}
        return RedactionRequest(
            folder_path=tmp_path,
            student_name="Test Student",
            documents=docs,
            detected_pii=detected,
            user_selections={},
        )

    def test_execute_stops_between_documents_when_cancelled(self, tmp_path):
        from src.services.redaction_service import RedactionService

        req = self._make_request(tmp_path, ("a.pdf", "b.pdf", "c.pdf"))
        # execute() calls should_cancel() exactly once per iteration, before
        # processing: first returns False (doc 1 runs), second returns True.
        flags = iter([False, True])
        results = RedactionService().execute(req, should_cancel=lambda: next(flags))

        assert results.cancelled is True
        assert len(results.document_results) == 1

    def test_execute_without_cancel_processes_all(self, tmp_path):
        from src.services.redaction_service import RedactionService

        req = self._make_request(tmp_path, ("a.pdf", "b.pdf"))
        results = RedactionService().execute(req)
        assert results.cancelled is False
        assert len(results.document_results) == 2

    def test_cancelled_run_is_recorded_in_the_audit_log(self, tmp_path):
        from src.services.redaction_service import RedactionService

        req = self._make_request(tmp_path, ("a.pdf", "b.pdf", "c.pdf"))
        flags = iter([False, True])
        results = RedactionService().execute(req, should_cancel=lambda: next(flags))
        assert "RUN CANCELLED" in results.log_content

    def test_cancel_endpoint_sets_flag(self):
        from backend import main as backend_main

        backend_main._redaction_control["cancel_requested"] = False
        try:
            r = client.post("/api/redact/cancel")
            assert r.status_code == 200
            assert backend_main._redaction_control["cancel_requested"] is True
        finally:
            # Never leave the flag set — a later test would phantom-cancel.
            backend_main._redaction_control["cancel_requested"] = False
