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


def _detect(pdf, student_name, **kwargs):
    body = {
        "pdf_paths": [str(pdf)],
        "student_name": student_name,
        "parent_names": kwargs.get("parent_names", []),
        "family_names": [],
        "organisation_names": kwargs.get("organisation_names", []),
    }
    res = client.post("/api/pii/detect", json=body)
    assert res.status_code == 200, res.text
    return res.json()["documents"][0]


def test_deidentify_writes_labelled_text_file():
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Student Joe Bloggs attended today.")

        doc0 = _detect(pdf, "Joe Bloggs")
        selected = [f"{pdf}_{i}" for i in range(len(doc0["matches"]))]

        res = client.post("/api/deidentify", json={
            "folder_path": tmp,
            "student_name": "Joe Bloggs",
            "documents": [str(pdf)],
            "selected_keys": selected,
        })
        assert res.status_code == 200, res.text
        data = res.json()

        assert data["successfully_deidentified"] == 1
        out = Path(data["document_results"][0]["output_path"])
        assert out.suffix == ".txt"
        body = out.read_text(encoding="utf-8")
        assert "[Student]" in body
        assert "Bloggs" not in body


def test_deidentify_honours_only_selected_keys():
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Joe Bloggs and parent Mary Bloggs attended.")

        doc0 = _detect(pdf, "Joe Bloggs", parent_names=["Mary Bloggs"])
        assert len(doc0["matches"]) >= 2

        # Select nothing at all — the output must still be produced, untouched.
        res = client.post("/api/deidentify", json={
            "folder_path": tmp,
            "student_name": "Joe Bloggs",
            "parent_names": ["Mary Bloggs"],
            "documents": [str(pdf)],
            "selected_keys": [],
        })
        assert res.status_code == 200, res.text
        out = Path(res.json()["document_results"][0]["output_path"])
        body = out.read_text(encoding="utf-8")
        assert "Joe Bloggs" in body


def test_key_file_is_outside_the_output_folder():
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Joe Bloggs attended today.")

        doc0 = _detect(pdf, "Joe Bloggs")
        selected = [f"{pdf}_{i}" for i in range(len(doc0["matches"]))]

        res = client.post("/api/deidentify", json={
            "folder_path": tmp,
            "student_name": "Joe Bloggs",
            "documents": [str(pdf)],
            "selected_keys": selected,
        })
        assert res.status_code == 200, res.text
        data = res.json()

        key_path = Path(data["key_file_path"])
        output_folder = Path(data["output_folder"])
        assert key_path.exists()
        assert key_path.parent == Path(tmp)
        assert output_folder not in key_path.parents

        # Every file in the output folder must be safe to upload.
        for f in output_folder.iterdir():
            assert "DO-NOT-UPLOAD" not in f.name


def test_audit_log_contains_no_real_names():
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Joe Bloggs attended today.")

        doc0 = _detect(pdf, "Joe Bloggs")
        selected = [f"{pdf}_{i}" for i in range(len(doc0["matches"]))]

        res = client.post("/api/deidentify", json={
            "folder_path": tmp,
            "student_name": "Joe Bloggs",
            "documents": [str(pdf)],
            "selected_keys": selected,
        })
        assert res.status_code == 200, res.text
        log = res.json()["log_content"]
        assert "Bloggs" not in log
        assert "[Student]" in log


def test_missing_cache_returns_400_with_the_expected_message():
    """The frontend clears its detection fingerprint on this exact wording."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "never_detected.pdf"
        _make_pdf(pdf, "Joe Bloggs attended today.")

        res = client.post("/api/deidentify", json={
            "folder_path": tmp,
            "student_name": "Joe Bloggs",
            "documents": [str(pdf)],
            "selected_keys": [],
        })
        assert res.status_code == 400
        assert "no cached detection data" in res.json()["detail"].lower()


def test_response_shape_survives_scanned_document_warnings():
    """OcrWarning is a typed model — a Dict[str, int] would 500 here."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Joe Bloggs attended today.")

        doc0 = _detect(pdf, "Joe Bloggs")
        selected = [f"{pdf}_{i}" for i in range(len(doc0["matches"]))]

        res = client.post("/api/deidentify", json={
            "folder_path": tmp,
            "student_name": "Joe Bloggs",
            "documents": [str(pdf)],
            "selected_keys": selected,
        })
        assert res.status_code == 200, res.text
        data = res.json()
        assert isinstance(data["ocr_warnings"], list)
        assert isinstance(data["verification_failures"], list)
        assert "image_warnings" in data["document_results"][0]


def test_cancel_flag_is_reset_on_entry():
    """A stale cancel from a previous run must not phantom-cancel this one."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Joe Bloggs attended today.")

        doc0 = _detect(pdf, "Joe Bloggs")
        selected = [f"{pdf}_{i}" for i in range(len(doc0["matches"]))]

        client.post("/api/redact/cancel")
        res = client.post("/api/deidentify", json={
            "folder_path": tmp,
            "student_name": "Joe Bloggs",
            "documents": [str(pdf)],
            "selected_keys": selected,
        })
        assert res.status_code == 200, res.text
        assert res.json()["cancelled"] is False
