"""
One unreadable document must not abort a detection run — and must not
vanish from it either. The service lists it in failed_documents with the
reason, the API passes that list through, and the review screen shows it.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from backend.main import app
from src.services.detection_service import DetectionService

client = TestClient(app)


def _make_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=12)
    doc.save(str(path))
    doc.close()


def _make_corrupt_pdf(path: Path) -> None:
    path.write_bytes(b"%PDF-1.4\nthis is not a real pdf\n")


class TestServiceKeepsGoing:

    def test_unreadable_document_is_reported_not_raised(self, tmp_path):
        good = tmp_path / "good.pdf"
        bad = tmp_path / "bad.pdf"
        _make_pdf(good, "Student Joe Bloggs attended the review.")
        _make_corrupt_pdf(bad)

        service = DetectionService(student_name="Joe Bloggs")
        results = service.detect_all([bad, good])

        assert results.documents == [good]
        assert [p for p, _ in results.failed_documents] == [bad]
        assert results.failed_documents[0][1]  # a reason, not an empty string
        assert bad not in results.pii_by_document
        assert any(m.text == "Joe Bloggs" for m in results.pii_by_document[good].matches)

    def test_a_clean_run_reports_no_failures(self, tmp_path):
        good = tmp_path / "good.pdf"
        _make_pdf(good, "Student Joe Bloggs attended the review.")
        results = DetectionService(student_name="Joe Bloggs").detect_all([good])
        assert results.failed_documents == []
        assert results.documents == [good]


class TestApiPassesFailuresThrough:

    def test_detect_returns_the_failed_document_with_its_reason(self, tmp_path):
        good = tmp_path / "good.pdf"
        bad = tmp_path / "Billy Bob report.pdf"
        _make_pdf(good, "Student Joe Bloggs attended the review.")
        _make_corrupt_pdf(bad)

        resp = client.post("/api/pii/detect", json={
            "pdf_paths": [str(good), str(bad)],
            "student_name": "Joe Bloggs",
            "parent_names": [], "family_names": [], "organisation_names": [],
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [d["path"] for d in body["documents"]] == [str(good)]
        assert body["failed_documents"] == [{
            "path": str(bad),
            "filename": "Billy Bob report.pdf",
            "reason": body["failed_documents"][0]["reason"],
        }]
        assert body["failed_documents"][0]["reason"]

    def test_paste_detection_has_an_empty_failed_list(self):
        resp = client.post("/api/text/detect", json={
            "text": "Student Joe Bloggs attended.",
            "student_name": "Joe Bloggs",
            "parent_names": [], "family_names": [], "organisation_names": [],
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["failed_documents"] == []
