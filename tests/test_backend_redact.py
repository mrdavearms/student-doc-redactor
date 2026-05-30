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
