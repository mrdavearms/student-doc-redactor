"""Folder endpoints accept only absolute paths."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_validate_rejects_a_relative_path():
    # A relative path resolves against the backend's own working directory,
    # never a folder the user meant — "." used to validate as a real folder.
    for path in (".", "src", "Documents"):
        body = client.post("/api/folder/validate", json={"folder_path": path}).json()
        assert body["exists"] is False
        assert body["is_directory"] is False


def test_process_rejects_a_relative_path():
    resp = client.post("/api/folder/process", json={"folder_path": "."})
    assert resp.status_code == 400
    assert "Folder not found" in resp.json()["detail"]


def test_process_rejects_a_file_path(tmp_path):
    f = tmp_path / "report.pdf"
    f.write_bytes(b"%PDF-")
    resp = client.post("/api/folder/process", json={"folder_path": str(f)})
    assert resp.status_code == 400
