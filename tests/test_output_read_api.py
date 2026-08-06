import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def _read(folder, path):
    return client.post("/api/output/read",
                       json={"output_folder": str(folder), "file_path": str(path)})


def test_reads_a_deidentified_file():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "report_deidentified.txt"
        f.write_text("[Student] is in Year 3.", encoding="utf-8")
        res = _read(tmp, f)
        assert res.status_code == 200
        assert res.json()["content"] == "[Student] is in Year 3."


def test_refuses_a_path_outside_the_folder():
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
        f = Path(other) / "report_deidentified.txt"
        f.write_text("secret")
        assert _read(tmp, f).status_code == 400


def test_refuses_traversal():
    with tempfile.TemporaryDirectory() as tmp:
        inner = Path(tmp) / "deidentified"
        inner.mkdir()
        secret = Path(tmp) / "original_deidentified.txt"
        secret.write_text("outside")
        res = _read(inner, inner / ".." / "original_deidentified.txt")
        assert res.status_code == 400


def test_refuses_quarantined_files():
    """UNVERIFIED text may contain PII — it must be opened deliberately."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "report.UNVERIFIED.txt"
        f.write_text("possibly leaky")
        assert _read(tmp, f).status_code == 400


def test_refuses_the_key_file():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "DO-NOT-UPLOAD-name-key.txt"
        f.write_text("[Student] -> Billy Bob")
        assert _read(tmp, f).status_code == 400


def test_refuses_arbitrary_files():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "notes.txt"
        f.write_text("private notes")
        assert _read(tmp, f).status_code == 400


def test_refuses_oversized_files():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "big_deidentified.txt"
        f.write_text("x" * (2 * 1024 * 1024 + 1))
        assert _read(tmp, f).status_code == 400


def test_auth_middleware_covers_the_route(monkeypatch):
    monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit")
    res = client.post("/api/output/read",
                      json={"output_folder": "/x", "file_path": "/x/y"})
    assert res.status_code == 401
