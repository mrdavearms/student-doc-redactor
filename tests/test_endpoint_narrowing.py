"""Task 16: the token holder can do less (preflight bypass, folder open, relative
paths, preview of arbitrary PDFs)."""

import tempfile
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend.main import app

client = TestClient(app)

pytestmark = pytest.mark.strict_detect

_NAMES = {"student_name": "Joe Bloggs", "parent_names": [],
          "family_names": [], "organisation_names": []}


def _make_pdf(path, text="Student Joe Bloggs attended Dummy School."):
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), text, fontsize=12)
    doc.save(str(path))
    doc.close()


def test_options_without_preflight_headers_requires_token(monkeypatch):
    monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
    assert client.options("/api/redact").status_code == 401


def test_real_preflight_still_passes_without_token(monkeypatch):
    monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
    r = client.options("/api/redact", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-api-token,content-type",
    })
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_folder_open_refuses_a_file(tmp_path):
    f = tmp_path / "a.pdf"
    _make_pdf(f)
    r = client.post("/api/folder/open", json={"folder_path": str(f)})
    assert r.status_code == 400
    assert str(tmp_path) not in r.json()["detail"]


def test_folder_open_refuses_relative_path():
    r = client.post("/api/folder/open", json={"folder_path": "."})
    assert r.status_code == 400


def test_file_process_refuses_relative_path():
    r = client.post("/api/file/process", json={"file_path": "README.md"})
    assert r.status_code == 400


def test_file_validate_refuses_relative_path():
    r = client.post("/api/file/validate", json={"file_path": "README.md"})
    assert r.status_code == 400


def test_preview_refuses_unrelated_pdf(tmp_path):
    pdf = tmp_path / "unrelated.pdf"
    _make_pdf(pdf)
    r = client.post("/api/preview", json={"pdf_path": str(pdf), "page_num": 0})
    assert r.status_code == 403
    assert str(tmp_path) not in r.json()["detail"]


def test_preview_allows_detected_document_and_its_output(tmp_path):
    pdf = tmp_path / "report.pdf"
    _make_pdf(pdf)
    assert client.post("/api/folder/process", json={"folder_path": str(tmp_path)}).status_code == 200
    det = client.post("/api/pii/detect", json={
        "pdf_paths": [str(pdf)], "student_name": "Joe Bloggs",
        "parent_names": [], "family_names": [], "organisation_names": [],
    })
    assert det.status_code == 200, det.text
    assert client.post("/api/preview", json={"pdf_path": str(pdf), "page_num": 0}).status_code == 200

    red = client.post("/api/redact", json={
        "folder_path": str(tmp_path), "student_name": "Joe Bloggs",
        "documents": [str(pdf)], "selected_keys": [f"{pdf}_0"],
        "folder_action": "overwrite", "detected_pii": {},
    })
    assert red.status_code == 200, red.text
    out = red.json()["document_results"][0]
    produced = out["output_path"] or out["quarantine_path"]
    assert produced
    assert client.post("/api/preview", json={"pdf_path": produced, "page_num": 0}).status_code == 200


def test_discard_clears_previewable(tmp_path):
    pdf = tmp_path / "report.pdf"
    _make_pdf(pdf)
    main._previewable.add(str(pdf.resolve()))
    client.post("/api/detection/discard")
    assert not main._previewable
    assert client.post("/api/preview", json={"pdf_path": str(pdf), "page_num": 0}).status_code == 403


def test_detect_refuses_unprocessed_path(tmp_path):
    pdf = tmp_path / "unrelated.pdf"
    _make_pdf(pdf)
    r = client.post("/api/pii/detect", json={"pdf_paths": [str(pdf)], **_NAMES})
    assert r.status_code == 403
    assert str(tmp_path) not in r.json()["detail"]
    # and it did not become previewable by the back door
    assert client.post("/api/preview", json={"pdf_path": str(pdf), "page_num": 0}).status_code == 403


def test_detect_allows_processed_folder_documents(tmp_path):
    pdf = tmp_path / "report.pdf"
    _make_pdf(pdf)
    other = tmp_path.parent / "elsewhere.pdf"
    _make_pdf(other)
    assert client.post("/api/folder/process", json={"folder_path": str(tmp_path)}).status_code == 200
    ok = client.post("/api/pii/detect", json={"pdf_paths": [str(pdf)], **_NAMES})
    assert ok.status_code == 200, ok.text
    bad = client.post("/api/pii/detect", json={"pdf_paths": [str(other)], **_NAMES})
    assert bad.status_code == 403


def test_detect_allows_word_converted_document(tmp_path, monkeypatch):
    converted = tmp_path / "temp-root" / "001" / "Report.pdf"
    converted.parent.mkdir(parents=True)
    _make_pdf(converted)
    folder = tmp_path / "docs"
    folder.mkdir()

    class _Results:
        pdf_files, converted_files = [], [converted]
        failed_conversions, password_protected = [], []
        total_files = processable_count = 1
        flagged_count = 0

    monkeypatch.setattr(main.ConversionService, "process_folder", lambda self, f: _Results())
    assert client.post("/api/folder/process", json={"folder_path": str(folder)}).status_code == 200
    r = client.post("/api/pii/detect", json={"pdf_paths": [str(converted)], **_NAMES})
    assert r.status_code == 200, r.text


def test_discard_clears_processable(tmp_path):
    pdf = tmp_path / "report.pdf"
    _make_pdf(pdf)
    client.post("/api/folder/process", json={"folder_path": str(tmp_path)})
    client.post("/api/detection/discard")
    r = client.post("/api/pii/detect", json={"pdf_paths": [str(pdf)], **_NAMES})
    assert r.status_code == 403


def test_preview_nul_byte_path_is_403_not_500():
    r = client.post("/api/preview", json={"pdf_path": "/tmp/a\x00b.pdf", "page_num": 0})
    assert r.status_code == 403
