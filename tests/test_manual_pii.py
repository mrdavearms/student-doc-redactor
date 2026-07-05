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


def _detect(pdf_path, student_name="Nobody Relevant"):
    return client.post("/api/pii/detect", json={
        "pdf_paths": [str(pdf_path)],
        "student_name": student_name,
        "parent_names": [],
        "family_names": [],
        "organisation_names": [],
    })


def test_manual_item_is_appended_and_redacted_end_to_end():
    """A manually-added item the engines missed must actually get redacted
    when the user selects it and runs /api/redact — proving the cache-append
    approach flows through the existing redact endpoint unmodified."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        # "STUDENTREF12345" is not a name, email, or any pattern the regex
        # or NER engines recognise — detection must find zero matches.
        _make_pdf(pdf, "Internal reference code STUDENTREF12345 for this file.")

        det = _detect(pdf)
        assert det.status_code == 200, det.text
        assert det.json()["documents"][0]["matches"] == []

        manual = client.post("/api/pii/manual", json={
            "doc_path": str(pdf),
            "text": "STUDENTREF12345",
            "page_num": 1,
        })
        assert manual.status_code == 200, manual.text
        body = manual.json()
        assert body["index"] == 0
        assert body["match"]["text"] == "STUDENTREF12345"
        assert body["match"]["source"] == "manual"
        assert body["match"]["confidence_label"] == "high"

        red = client.post("/api/redact", json={
            "folder_path": tmp,
            "student_name": "Nobody Relevant",
            "parent_names": [],
            "family_names": [],
            "organisation_names": [],
            "redact_header_footer": False,
            "documents": [str(pdf)],
            "detected_pii": {},
            "selected_keys": [f"{pdf}_0"],
            "folder_action": "overwrite",
        })
        assert red.status_code == 200, red.text
        result = red.json()["document_results"][0]
        assert result["success"] is True
        assert result["items_redacted"] == 1

        out_doc = fitz.open(result["output_path"])
        out_text = out_doc[0].get_text()
        out_doc.close()
        assert "STUDENTREF12345" not in out_text


def test_manual_item_rejects_text_under_3_chars():
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Some content.")
        _detect(pdf)

        resp = client.post("/api/pii/manual", json={
            "doc_path": str(pdf), "text": "Jo", "page_num": 1,
        })
        assert resp.status_code == 400
        assert "at least 3 characters" in resp.json()["detail"]


def test_manual_item_rejects_out_of_range_page():
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Some content.")
        _detect(pdf)

        resp = client.post("/api/pii/manual", json={
            "doc_path": str(pdf), "text": "Missed Name", "page_num": 5,
        })
        assert resp.status_code == 400
        assert "does not exist in this document" in resp.json()["detail"]


def test_manual_item_requires_prior_detection():
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Some content.")
        # No _detect(pdf) call — no cache entry exists for this path.

        resp = client.post("/api/pii/manual", json={
            "doc_path": str(pdf), "text": "Missed Name", "page_num": 1,
        })
        assert resp.status_code == 400
        assert "Run detection first" in resp.json()["detail"]
