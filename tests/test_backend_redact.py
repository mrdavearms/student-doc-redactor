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


class TestOcrWarningsResponse:
    """Regression: a redaction whose selected items sit on scanned (image-only)
    pages must return its results, not a 500. RedactionResultsResponse declared
    ocr_warnings as Dict[str, int], so the str filename failed validation and
    every scanned document — a mainstream case for this tool — errored out."""

    def _seed_cache(self, pdf, page_num=1):
        """Put one match on a page the extractor reported as image-only."""
        from backend import main as backend_main
        from src.core.pii_detector import PIIMatch

        backend_main._detection_cache[str(pdf)] = {
            "matches": [PIIMatch(
                text="Joe Bloggs", category="Student name", confidence=0.95,
                page_num=page_num, line_num=1, context="Joe Bloggs",
                source="regex", bbox=None,
            )],
            "text_data": {"pages": {}, "ocr_pages": [page_num]},
        }

    def test_scanned_page_returns_200_with_its_warnings(self, tmp_path):
        pdf = tmp_path / "scanned report.pdf"
        _make_pdf(pdf, "Joe Bloggs attended.")
        self._seed_cache(pdf)

        resp = client.post("/api/redact", json={
            "folder_path": str(tmp_path),
            "student_name": "Joe Bloggs",
            "parent_names": [], "family_names": [], "organisation_names": [],
            "redact_header_footer": False,
            "documents": [str(pdf)],
            "detected_pii": {},
            "selected_keys": [f"{pdf}_0"],
            "folder_action": None,
        })

        assert resp.status_code == 200, resp.text
        assert resp.json()["ocr_warnings"] == [
            {"filename": "scanned report.pdf", "count": 1}
        ]

    def _redact(self, tmp_path, pdf, keys):
        return client.post("/api/redact", json={
            "folder_path": str(tmp_path),
            "student_name": "Joe Bloggs",
            "parent_names": [], "family_names": [], "organisation_names": [],
            "redact_header_footer": False,
            "documents": [str(pdf)],
            "detected_pii": {},
            "selected_keys": keys,
            "folder_action": None,
        })

    def _seed(self, pdf, items, ocr_pages):
        from backend import main as backend_main
        from src.core.pii_detector import PIIMatch
        backend_main._detection_cache[str(pdf)] = {
            "matches": [PIIMatch(
                text=t, category="Student name", confidence=0.95,
                page_num=p, line_num=1, context=t, source="regex", bbox=None,
            ) for t, p in items],
            "text_data": {"pages": {}, "ocr_pages": ocr_pages},
        }

    def test_count_is_items_on_scanned_pages_not_warning_lines(self, tmp_path):
        """The summary says "N item(s) on image-only pages". N used to be the
        number of warning LINES, so three scanned-page items read as 1."""
        pdf = tmp_path / "scan.pdf"
        _make_pdf(pdf, "Joe Bloggs, Jane Bloggs and Ann Bloggs attended.")
        self._seed(pdf, [("Joe Bloggs", 1), ("Jane Bloggs", 1), ("Ann Bloggs", 1)], [1])

        resp = self._redact(tmp_path, pdf, [f"{pdf}_{i}" for i in range(3)])
        assert resp.status_code == 200, resp.text
        assert resp.json()["ocr_warnings"] == [{"filename": "scan.pdf", "count": 3}]

    def test_common_word_note_without_scanned_items_counts_zero(self, tmp_path):
        """A selected common-word name warns about the scanned page even with
        no item on it. That must not be reported as "1 item(s)"."""
        pdf = tmp_path / "mixed.pdf"
        _make_pdf(pdf, "Grace attended.")
        self._seed(pdf, [("Grace", 1)], [2])

        resp = self._redact(tmp_path, pdf, [f"{pdf}_0"])
        assert resp.status_code == 200, resp.text
        assert resp.json()["ocr_warnings"] == [{"filename": "mixed.pdf", "count": 0}]
        doc = resp.json()["document_results"][0]
        assert any("scanned" in w for w in doc["ocr_warnings"])

    def test_response_model_accepts_a_string_filename(self):
        """Guards the schema directly, so the shape can't regress to Dict[str, int]."""
        from backend.schemas import RedactionResultsResponse

        model = RedactionResultsResponse(
            redacted_folder="/tmp/redacted",
            document_results=[], log_content="", total_documents=1,
            successfully_redacted=1, verification_failures=[],
            ocr_warnings=[{"filename": "report.pdf", "count": 2}],
        )

        assert model.ocr_warnings[0].filename == "report.pdf"
        assert model.ocr_warnings[0].count == 2


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

    def test_cancelled_run_reports_full_requested_total(self, tmp_path):
        """total_documents must be the intended count, not just the processed
        count — otherwise a cancelled run reads as '1 of 1' instead of '1 of 3'
        and disagrees with the audit log (which already uses the full count)."""
        from src.services.redaction_service import RedactionService

        req = self._make_request(tmp_path, ("a.pdf", "b.pdf", "c.pdf"))
        flags = iter([False, True])
        results = RedactionService().execute(req, should_cancel=lambda: next(flags))

        assert len(results.document_results) == 1  # only one processed
        assert results.successfully_redacted == 1
        assert results.total_documents == 3        # but three were requested

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


class TestSourcePathInResults:
    """Each document result names the input path it came from. document_name
    alone is not unique: Report.docx converts to <temp>/001/Report.pdf, so it
    and a native Report.pdf in the same folder share a name — and the
    completion screen keyed its cards on that name."""

    def test_two_documents_with_one_filename_keep_separate_source_paths(self, tmp_path):
        a = tmp_path / "001" / "Report.pdf"
        b = tmp_path / "Report.pdf"
        a.parent.mkdir()
        _make_pdf(a, "Student Joe Bloggs attended the review.")
        _make_pdf(b, "Student Joe Bloggs attended the meeting.")

        det = client.post("/api/pii/detect", json={
            "pdf_paths": [str(a), str(b)],
            "student_name": "Joe Bloggs",
            "parent_names": [], "family_names": [], "organisation_names": [],
        })
        assert det.status_code == 200, det.text

        red = client.post("/api/redact", json={
            "folder_path": str(tmp_path),
            "student_name": "Joe Bloggs",
            "parent_names": [], "family_names": [], "organisation_names": [],
            "redact_header_footer": False,
            "documents": [str(a), str(b)],
            "detected_pii": {},
            "selected_keys": [f"{a}_0", f"{b}_0"],
            "folder_action": "overwrite",
        })
        assert red.status_code == 200, red.text
        results = red.json()["document_results"]
        assert [r["document_name"] for r in results] == ["Report.pdf", "Report.pdf"]
        assert [r["source_path"] for r in results] == [str(a), str(b)]


class TestOutputFolderHoldingOriginals:
    """redaction_log.txt lists every removed name and sits beside the originals,
    so an output folder that is or contains that folder must be flagged."""

    def _run(self, tmp, out_path):
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Student Joe Bloggs attended.")
        det = client.post("/api/pii/detect", json={
            "pdf_paths": [str(pdf)], "student_name": "Joe Bloggs",
            "parent_names": [], "family_names": [], "organisation_names": [],
        })
        assert det.status_code == 200, det.text
        body = {
            "folder_path": tmp, "student_name": "Joe Bloggs",
            "parent_names": [], "family_names": [], "organisation_names": [],
            "redact_header_footer": False, "documents": [str(pdf)],
            "detected_pii": {}, "selected_keys": [f"{pdf}_0"],
            "folder_action": "overwrite",
        }
        if out_path is not None:
            body["custom_output_path"] = str(out_path)
        red = client.post("/api/redact", json=body)
        assert red.status_code == 200, red.text
        return red.json()

    def test_redact_flags_output_folder_holding_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            same = self._run(tmp, Path(tmp))
            assert same["output_folder_holds_originals"] is True
        with tempfile.TemporaryDirectory() as tmp:
            outer = Path(tmp) / "outer"
            inner = outer / "inner"
            inner.mkdir(parents=True)
            parent = self._run(str(inner), outer)
            assert parent["output_folder_holds_originals"] is True

    def test_separate_output_folder_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert self._run(tmp, None)["output_folder_holds_originals"] is False

    def test_redact_log_carries_do_not_share_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = self._run(tmp, None)
            first = body["log_content"].splitlines()[0]
            assert "contains the names that were removed" in first
