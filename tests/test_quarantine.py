"""
What happens to a redacted file that FAILS post-redaction verification.

The output of a failed verification may still show PII, so the one thing that
must never happen is for it to keep a name that says "_redacted".
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

from pathlib import Path

import fitz
import pytest

from src.services import deidentification_service as ds_module
from src.services import redaction_service as rs_module
from src.services.deidentification_service import (
    DeidentificationService, DeidentifyRequest,
)
from src.services.redaction_service import RedactionService, RedactionRequest


def _make_pdf(path: Path, text: str = "Joe Bloggs attended.") -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def _failing_service() -> RedactionService:
    """A service whose OCR verification always reports PII still visible."""
    service = RedactionService()
    service._redactor.verify_redaction_ocr = lambda path, texts: (
        False, ["Page 1: 'Joe' still visible after redaction"]
    )
    return service


def _request(tmp_path: Path, doc: Path) -> RedactionRequest:
    from src.core.pii_detector import PIIMatch

    match = PIIMatch(
        text="Joe", category="Student name", confidence=0.95,
        page_num=1, line_num=1, context="Joe Bloggs attended.",
    )
    return RedactionRequest(
        folder_path=tmp_path,
        student_name="Joe Bloggs",
        documents=[doc],
        detected_pii={doc: {"matches": [match],
                            "text_data": {"pages": {}, "ocr_pages": []}}},
        user_selections={f"{doc}_0": True},
    )


class TestQuarantine:
    def test_a_failed_file_is_renamed_out_of_the_way(self, tmp_path):
        doc = _make_pdf(tmp_path / "report.pdf")

        results = _failing_service().execute(_request(tmp_path, doc))
        result = results.document_results[0]

        assert result.success is False
        assert result.quarantine_path is not None
        assert result.quarantine_path.exists()
        assert result.output_path is None
        assert list(results.redacted_folder.glob("*_redacted.pdf")) == []

    def test_a_second_failure_replaces_the_first_quarantined_file(self, tmp_path):
        """
        The Windows case. Run one renames its output away, so run two gets the
        plain "_redacted.pdf" name back and its quarantine target already
        exists. Path.rename raises FileExistsError there (POSIX replaces
        silently), and the swallowed error left run two's unverified output
        sitting under a name that says it was redacted.
        """
        doc = _make_pdf(tmp_path / "report.pdf")
        service = _failing_service()

        first = service.execute(_request(tmp_path, doc)).document_results[0]
        assert first.quarantine_path.exists()

        second = service.execute(_request(tmp_path, doc)).document_results[0]

        assert second.quarantine_path == first.quarantine_path
        assert second.quarantine_path.exists()
        assert second.output_path is None
        assert list(second.quarantine_path.parent.glob("*_redacted.pdf")) == []

    def test_a_file_that_cannot_be_set_aside_does_not_survive(self, tmp_path, monkeypatch):
        """
        If the move fails outright, the unverified file must not be left behind
        wearing a "_redacted" name — better no output than a misleading one.
        """
        doc = _make_pdf(tmp_path / "report.pdf")

        def refuse(src, dst):
            raise OSError(17, "File exists")

        monkeypatch.setattr(rs_module.os, "replace", refuse)

        results = _failing_service().execute(_request(tmp_path, doc))
        result = results.document_results[0]

        assert result.success is False
        assert result.output_path is None
        assert result.quarantine_path is None
        assert result.error_message is not None
        assert list(results.redacted_folder.glob("*.pdf")) == []


class TestVerificationHandleIsReleased:
    def test_the_pdf_is_closed_even_when_verification_errors(self, tmp_path, monkeypatch):
        """
        An open handle locks the file on Windows — and the next thing the
        caller does after a verification error is try to move that same file.
        """
        from src.core import redactor as redactor_module

        pdf = _make_pdf(tmp_path / "report.pdf")
        opened = []

        real_open = redactor_module.fitz.open

        def tracking_open(*args, **kwargs):
            doc = real_open(*args, **kwargs)
            opened.append(doc)
            return doc

        monkeypatch.setattr(redactor_module.fitz, "open", tracking_open)
        monkeypatch.setattr(
            redactor_module.pytesseract, "image_to_string",
            lambda img: (_ for _ in ()).throw(RuntimeError("tesseract exploded")),
        )

        clean, failures = RedactionService()._redactor.verify_redaction_ocr(pdf, ["Joe"])

        assert clean is False
        assert any("verification error" in f for f in failures)
        assert opened and all(d.is_closed for d in opened)


# ── Two different documents that strip to the same output name ───────────

def _same_stem_pair(tmp_path):
    """
    Two DIFFERENT source documents whose names both strip to "Report" once the
    student and parent names are removed — the shape that makes their output
    filenames collide.
    """
    return (_make_pdf(tmp_path / "Billy Bob Report.pdf", "Billy Bob attended."),
            _make_pdf(tmp_path / "Sarah Bob Report.pdf", "Billy Bob attended."))


def _match():
    from src.core.pii_detector import PIIMatch
    return PIIMatch(text="Billy", category="Student name", confidence=0.95,
                    page_num=1, line_num=1, context="Billy Bob attended.")


class TestTwoDocumentsNeverShareAQuarantineFile:
    """
    A document that fails verification has its output renamed away, so the
    plain name is free again and the NEXT document with the same stripped stem
    takes it — then overwrites the first one's quarantined file. Two documents
    in, one file on disk, both results pointing at it, no warning.
    """

    def test_redact_keeps_both_quarantined_files(self, tmp_path):
        a, b = _same_stem_pair(tmp_path)
        m = _match()

        service = _failing_service()
        results = service.execute(RedactionRequest(
            folder_path=tmp_path, student_name="Billy Bob", documents=[a, b],
            detected_pii={d: {"matches": [m],
                              "text_data": {"pages": {}, "ocr_pages": []}}
                          for d in (a, b)},
            user_selections={f"{a}_0": True, f"{b}_0": True},
            parent_names=["Sarah Bob"],
        ))

        quarantined = [r.quarantine_path for r in results.document_results]
        assert all(q is not None for q in quarantined)
        assert len(set(quarantined)) == 2, "both documents claimed the same file"
        assert len(list(results.redacted_folder.glob("*.UNVERIFIED.pdf"))) == 2

    def test_deidentify_keeps_both_quarantined_files(self, tmp_path, monkeypatch):
        a, b = _same_stem_pair(tmp_path)
        m = _match()

        monkeypatch.setattr(ds_module, "verify_deidentified",
                            lambda text, selected, labels: ["Billy"])

        results = DeidentificationService().execute(DeidentifyRequest(
            folder_path=tmp_path, student_name="Billy Bob", documents=[a, b],
            detected_pii={d: {"matches": [m], "text_data": {
                "pages": {1: {"text": "Billy Bob attended.", "method": "native"}},
                "ocr_pages": []}} for d in (a, b)},
            user_selections={f"{a}_0": True, f"{b}_0": True},
            parent_names=["Sarah Bob"],
        ))

        quarantined = [r.quarantine_path for r in results.document_results]
        assert all(q is not None for q in quarantined)
        assert len(set(quarantined)) == 2, "both documents claimed the same file"
        assert len(list(Path(results.output_folder).glob("*.UNVERIFIED.txt"))) == 2

    def test_a_rerun_of_one_document_does_not_accumulate_copies(self, tmp_path):
        """
        The other half of the contract: claiming is per RUN, so re-running the
        same document overwrites its own quarantine instead of leaving a trail
        of _2, _3, _4 files behind.
        """
        doc = _make_pdf(tmp_path / "report.pdf")
        service = _failing_service()

        for _ in range(3):
            results = service.execute(_request(tmp_path, doc))

        assert len(list(results.redacted_folder.glob("*.UNVERIFIED.pdf"))) == 1
