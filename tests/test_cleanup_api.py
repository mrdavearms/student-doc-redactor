"""Tests for /api/cleanup/list and /api/cleanup endpoints."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


class TestCleanupList:
    def test_returns_redacted_pdfs(self, tmp_path):
        (tmp_path / "doc_redacted.pdf").write_bytes(b"fake")
        (tmp_path / "other.pdf").write_bytes(b"fake")
        r = client.post("/api/cleanup/list", json={"output_path": str(tmp_path)})
        assert r.status_code == 200
        files = r.json()["files"]
        assert any("doc_redacted.pdf" in f for f in files)
        assert not any("other.pdf" in f for f in files)

    def test_returns_unverified_pdfs(self, tmp_path):
        (tmp_path / "doc.UNVERIFIED.pdf").write_bytes(b"fake")
        r = client.post("/api/cleanup/list", json={"output_path": str(tmp_path)})
        assert r.status_code == 200
        assert any("UNVERIFIED.pdf" in f for f in r.json()["files"])

    def test_returns_empty_for_nonexistent_folder(self):
        r = client.post("/api/cleanup/list", json={"output_path": "/nonexistent/path/xyz_abc"})
        assert r.status_code == 200
        assert r.json()["files"] == []

    def test_ignores_non_matching_pdfs(self, tmp_path):
        (tmp_path / "report.pdf").write_bytes(b"fake")
        (tmp_path / "original.pdf").write_bytes(b"fake")
        r = client.post("/api/cleanup/list", json={"output_path": str(tmp_path)})
        assert r.status_code == 200
        assert r.json()["files"] == []

    def test_returns_both_patterns_together(self, tmp_path):
        (tmp_path / "a_redacted.pdf").write_bytes(b"fake")
        (tmp_path / "b.UNVERIFIED.pdf").write_bytes(b"fake")
        (tmp_path / "c.pdf").write_bytes(b"fake")
        r = client.post("/api/cleanup/list", json={"output_path": str(tmp_path)})
        assert r.status_code == 200
        files = r.json()["files"]
        assert len(files) == 2
        assert any("a_redacted.pdf" in f for f in files)
        assert any("b.UNVERIFIED.pdf" in f for f in files)


class TestCleanup:
    def test_deletes_redacted_pdf(self, tmp_path):
        f = tmp_path / "doc_redacted.pdf"
        f.write_bytes(b"fake")
        r = client.post("/api/cleanup", json={"output_folder": str(tmp_path), "file_paths": [str(f)]})
        assert r.status_code == 200
        assert not f.exists()
        assert str(f) in r.json()["deleted"]
        assert r.json()["failed"] == []

    def test_rejects_path_outside_folder(self, tmp_path):
        sibling = tmp_path.parent / f"evil_redacted_{tmp_path.name}.pdf"
        sibling.write_bytes(b"fake")
        try:
            r = client.post("/api/cleanup", json={
                "output_folder": str(tmp_path),
                "file_paths": [str(sibling)],
            })
            assert r.status_code == 200
            assert sibling.exists()
            failed = r.json()["failed"]
            assert len(failed) == 1
            assert "outside output folder" in failed[0]["reason"]
        finally:
            sibling.unlink(missing_ok=True)

    def test_rejects_path_traversal(self, tmp_path):
        traversal = str(tmp_path / ".." / "victim_redacted.pdf")
        r = client.post("/api/cleanup", json={
            "output_folder": str(tmp_path),
            "file_paths": [traversal],
        })
        assert r.status_code == 200
        failed = r.json()["failed"]
        assert len(failed) == 1
        assert "outside output folder" in failed[0]["reason"]

    def test_rejects_non_pdf_extension(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_bytes(b"fake")
        r = client.post("/api/cleanup", json={"output_folder": str(tmp_path), "file_paths": [str(f)]})
        assert r.status_code == 200
        assert f.exists()
        assert "not a PDF" in r.json()["failed"][0]["reason"]

    def test_nonexistent_file_is_silent_noop(self, tmp_path):
        r = client.post("/api/cleanup", json={
            "output_folder": str(tmp_path),
            "file_paths": [str(tmp_path / "gone_redacted.pdf")],
        })
        assert r.status_code == 200
        assert r.json()["deleted"] == []
        assert r.json()["failed"] == []

    def test_returns_400_for_nonexistent_folder(self):
        r = client.post("/api/cleanup", json={
            "output_folder": "/nonexistent/folder_xyz_abc",
            "file_paths": [],
        })
        assert r.status_code == 400

    def test_deletes_multiple_files(self, tmp_path):
        files = [tmp_path / f"doc{i}_redacted.pdf" for i in range(3)]
        for f in files:
            f.write_bytes(b"fake")
        r = client.post("/api/cleanup", json={
            "output_folder": str(tmp_path),
            "file_paths": [str(f) for f in files],
        })
        assert r.status_code == 200
        assert len(r.json()["deleted"]) == 3
        assert all(not f.exists() for f in files)

    def test_mixed_valid_and_invalid_paths(self, tmp_path):
        good = tmp_path / "ok_redacted.pdf"
        good.write_bytes(b"fake")
        sibling = tmp_path.parent / f"bad_redacted_{tmp_path.name}.pdf"
        sibling.write_bytes(b"fake")
        try:
            r = client.post("/api/cleanup", json={
                "output_folder": str(tmp_path),
                "file_paths": [str(good), str(sibling)],
            })
            assert r.status_code == 200
            assert not good.exists()
            assert sibling.exists()
            assert len(r.json()["deleted"]) == 1
            assert len(r.json()["failed"]) == 1
        finally:
            sibling.unlink(missing_ok=True)

    def test_rejects_pdf_not_matching_output_patterns(self, tmp_path):
        """An original student PDF must never be deletable via cleanup."""
        f = tmp_path / "original student report.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        r = client.post("/api/cleanup", json={
            "output_folder": str(tmp_path), "file_paths": [str(f)],
        })
        assert r.status_code == 200
        assert f.exists()
        assert "not a redaction output file" in r.json()["failed"][0]["reason"]

    def test_deletes_redacted_pattern(self, tmp_path):
        f = tmp_path / "report_redacted.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        r = client.post("/api/cleanup", json={
            "output_folder": str(tmp_path), "file_paths": [str(f)],
        })
        assert r.status_code == 200
        assert not f.exists()

    def test_deletes_unverified_pattern(self, tmp_path):
        f = tmp_path / "report_redacted.UNVERIFIED.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        r = client.post("/api/cleanup", json={
            "output_folder": str(tmp_path), "file_paths": [str(f)],
        })
        assert r.status_code == 200
        assert not f.exists()
