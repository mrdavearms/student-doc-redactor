"""
Folder scanning: which files in a folder the app will actually process.

The scan used to be glob('*.pdf'), which is case-SENSITIVE on macOS and
case-INSENSITIVE on Windows — so the same folder produced different results on
the two platforms this app ships on, with no error to explain the difference.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

from pathlib import Path

import fitz

from src.services.conversion_service import ConversionService


def _make_pdf(path: Path, text: str = "Joe Bloggs attended.") -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


class TestExtensionCaseIsIgnored:
    def test_uppercase_pdf_extension_is_found(self, tmp_path):
        """School photocopiers routinely emit SKMBT_C25016.PDF."""
        scan = _make_pdf(tmp_path / "SKMBT_C25016.PDF")
        results = ConversionService().process_folder(tmp_path)

        assert scan in results.pdf_files
        assert results.processable_count == 1

    def test_mixed_case_folder_processes_every_document(self, tmp_path):
        """
        The dangerous shape: not an empty result the user would notice, but a
        folder where SOME documents are silently left out of the run.
        """
        lower = _make_pdf(tmp_path / "report.pdf")
        upper = _make_pdf(tmp_path / "SCAN.PDF")
        mixed = _make_pdf(tmp_path / "Term3.Pdf")

        results = ConversionService().process_folder(tmp_path)

        assert set(results.pdf_files) == {lower, upper, mixed}
        assert results.processable_count == 3

    def test_uppercase_word_extension_is_picked_up(self, tmp_path):
        """
        Whether it then converts depends on LibreOffice being installed, which
        differs by machine — so assert only that the file was SEEN. Being
        counted at all is the thing that used to fail on macOS.
        """
        (tmp_path / "Support Plan.DOCX").write_bytes(b"not really a docx")

        results = ConversionService().process_folder(tmp_path)

        assert results.total_files == 1

    def test_unrelated_extensions_are_still_ignored(self, tmp_path):
        (tmp_path / "notes.txt").write_text("hello")
        (tmp_path / "photo.PNG").write_bytes(b"\x89PNG")
        _make_pdf(tmp_path / "report.pdf")

        results = ConversionService().process_folder(tmp_path)

        assert results.total_files == 1

    def test_subfolders_are_not_descended_into(self, tmp_path):
        """Output folders live inside the input folder — they must stay out."""
        _make_pdf(tmp_path / "report.pdf")
        nested = tmp_path / "redacted"
        nested.mkdir()
        _make_pdf(nested / "report_redacted.pdf")

        results = ConversionService().process_folder(tmp_path)

        assert results.total_files == 1


# ── Where Word conversions are written ───────────────────────────────────

class TestConversionsStayOutOfTheUsersFolder:
    """
    Converted PDFs are unredacted copies of the student's document. They must
    not be left sitting next to the originals, where they get synced by
    OneDrive and swept up if the folder is dragged somewhere.
    """

    def test_folder_run_leaves_no_temp_folder_behind(self, tmp_path):
        _make_pdf(tmp_path / "report.pdf")
        (tmp_path / "plan.docx").write_bytes(b"not really a docx")

        ConversionService().process_folder(tmp_path)

        assert not (tmp_path / '.temp_converted').exists()

    def test_single_document_run_leaves_no_temp_folder_behind(self, tmp_path):
        doc = tmp_path / "plan.docx"
        doc.write_bytes(b"not really a docx")

        ConversionService().process_file(doc)

        assert not (tmp_path / '.temp_converted').exists()

    def test_converted_output_is_not_inside_the_source_folder(self, tmp_path):
        from src.core.document_converter import _conversion_dir

        assert not _conversion_dir().is_relative_to(tmp_path)

    def test_a_legacy_temp_folder_is_cleaned_up(self, tmp_path):
        """Existing installs have these on disk already — clear them on sight."""
        legacy = tmp_path / '.temp_converted'
        legacy.mkdir()
        _make_pdf(legacy / "Billy Bob Report.pdf")
        _make_pdf(tmp_path / "report.pdf")

        ConversionService().process_folder(tmp_path)

        assert not legacy.exists()

    def test_each_run_starts_from_an_empty_conversion_folder(self, tmp_path):
        from src.core.document_converter import _conversion_dir

        first = _conversion_dir()
        (first / "stale.pdf").write_bytes(b"%PDF-1.4")

        second = _conversion_dir()

        assert list(second.iterdir()) == []
