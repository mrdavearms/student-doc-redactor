"""
Document Converter
Converts Word documents to PDF using LibreOffice in headless mode.
"""

import atexit
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple
import fitz  # PyMuPDF


# Word documents are converted to PDF before anything else can read them, and
# those conversions are full, UNREDACTED copies of the student's document.
#
# They used to be written to "<the user's folder>/.temp_converted" and left
# there permanently — nothing ever deleted them. The dot-prefix hides the
# folder on macOS but means nothing on Windows, and school folders are
# routinely inside OneDrive, so unredacted copies of student documents were
# being synced to the cloud by an app whose promise is that nothing leaves the
# machine. Dragging the folder into an AI tool took them along too.
#
# They now live in the OS temp area instead, in a directory private to this
# backend process, cleared at the start of every conversion run and removed on
# a clean exit.
_TEMP_ROOT: Path | None = None


def _conversion_dir() -> Path:
    """
    An empty directory for this conversion run's PDFs, outside the user's
    folder.

    Cleared on each call: one conversion run supersedes the previous one, which
    is what the old in-folder behaviour did anyway by overwriting the same
    filenames.
    """
    global _TEMP_ROOT
    if _TEMP_ROOT is None:
        _TEMP_ROOT = Path(tempfile.mkdtemp(prefix="redaction-tool-"))
        atexit.register(shutil.rmtree, _TEMP_ROOT, True)

    converted = _TEMP_ROOT / "converted"
    shutil.rmtree(converted, ignore_errors=True)
    converted.mkdir(parents=True, exist_ok=True)
    return converted


def _remove_legacy_temp_dir(folder: Path) -> None:
    """
    Delete a ".temp_converted" folder left behind by an earlier version.

    Only ever created by this app, and holding only unredacted conversions it
    produced, so removing it is the privacy-preserving action rather than a
    destructive one. Best-effort: a file held open by another program is not
    worth failing a run over.
    """
    shutil.rmtree(folder / '.temp_converted', ignore_errors=True)


def _libreoffice_install_hint() -> str:
    """Return a platform-appropriate install instruction for LibreOffice."""
    system = platform.system()
    if system == "Windows":
        return "LibreOffice not found. Download from libreoffice.org and install it."
    elif system == "Darwin":
        return "LibreOffice not found. Install via: brew install --cask libreoffice"
    else:
        return "LibreOffice not found. Install via your package manager (e.g. sudo apt install libreoffice)."


class DocumentConverter:
    """Handles conversion of Word documents to PDF"""

    def __init__(self):
        from binary_resolver import resolve_libreoffice
        self.soffice_path = resolve_libreoffice()

    def check_libreoffice_installed(self) -> Tuple[bool, str]:
        """
        Check if LibreOffice is installed and accessible

        Returns:
            Tuple of (is_installed, message)
        """
        if self.soffice_path and Path(self.soffice_path).exists():
            return True, "LibreOffice installed"
        return False, _libreoffice_install_hint()

    def convert_to_pdf(self, input_file: Path, output_dir: Path) -> Tuple[bool, str, Path]:
        """
        Convert a Word document to PDF

        Args:
            input_file: Path to .doc or .docx file
            output_dir: Directory to save the PDF

        Returns:
            Tuple of (success, message, output_path)
        """
        if input_file.suffix.lower() not in ['.doc', '.docx']:
            return False, f"Not a Word document: {input_file.suffix}", None

        if not self.soffice_path:
            return False, _libreoffice_install_hint(), None

        try:
            # Use LibreOffice in headless mode to convert
            result = subprocess.run(
                [
                    self.soffice_path,
                    '--headless',
                    '--convert-to', 'pdf',
                    '--outdir', str(output_dir),
                    str(input_file)
                ],
                capture_output=True,
                text=True,
                timeout=60  # 60 second timeout for conversion
            )

            # Expected output filename
            output_file = output_dir / f"{input_file.stem}.pdf"

            if result.returncode == 0 and output_file.exists():
                return True, "Conversion successful", output_file
            else:
                error_msg = result.stderr if result.stderr else result.stdout
                return False, f"Conversion failed: {error_msg}", None

        except subprocess.TimeoutExpired:
            return False, "Conversion timed out (>60s)", None
        except Exception as e:
            return False, f"Error during conversion: {str(e)}", None

    def check_pdf_password_protected(self, pdf_path: Path) -> Tuple[bool, str]:
        """
        Check if a PDF is password protected

        Args:
            pdf_path: Path to PDF file

        Returns:
            Tuple of (is_protected, message)
        """
        try:
            doc = fitz.open(str(pdf_path))
            if doc.is_encrypted:
                doc.close()
                return True, "PDF is password protected"
            doc.close()
            return False, "PDF is accessible"
        except Exception as e:
            return True, f"Error checking PDF: {str(e)}"

    def process_file(self, file_path: Path) -> Dict:
        """
        Process a single document (the single-document redaction path).

        Same result shape as process_folder() so every downstream step —
        detection, review, redaction — is identical for one file or many.

        Args:
            file_path: Path to a .pdf, .doc or .docx file

        Returns:
            Dictionary with the same keys as process_folder()
        """
        results = {
            'pdf_files': [],
            'converted_files': [],
            'failed_conversions': [],
            'password_protected': []
        }

        suffix = file_path.suffix.lower()

        _remove_legacy_temp_dir(file_path.parent)

        if suffix in ('.doc', '.docx'):
            success, message, output_path = self.convert_to_pdf(
                file_path, _conversion_dir()
            )
            if success:
                results['converted_files'].append(output_path)
            else:
                results['failed_conversions'].append((file_path, message))
        elif suffix == '.pdf':
            is_protected, message = self.check_pdf_password_protected(file_path)
            if is_protected:
                results['password_protected'].append(file_path)
            else:
                results['pdf_files'].append(file_path)
        else:
            results['failed_conversions'].append(
                (file_path, f"Unsupported file type: {file_path.suffix or 'no extension'}")
            )

        return results

    def process_folder(self, folder_path: Path) -> Dict:
        """
        Process all documents in a folder

        Args:
            folder_path: Path to folder containing documents

        Returns:
            Dictionary with conversion results:
            {
                'pdf_files': List[Path],  # Original PDFs
                'converted_files': List[Path],  # Converted PDFs
                'failed_conversions': List[Tuple[Path, str]],  # Failed files with reason
                'password_protected': List[Path]  # Password-protected PDFs
            }
        """
        results = {
            'pdf_files': [],
            'converted_files': [],
            'failed_conversions': [],
            'password_protected': []
        }

        _remove_legacy_temp_dir(folder_path)
        temp_dir = _conversion_dir()

        # Find all documents.
        #
        # Matched on the lower-cased suffix, NOT with glob('*.pdf'): pathlib
        # globbing is case-SENSITIVE on macOS, so a scanner-produced
        # "SKMBT_C25016.PDF" was invisible there while the same file matched
        # fine on Windows. In a mixed folder that meant a document was skipped
        # silently — no error, just one fewer file in the results. Single-
        # document mode already compared suffix.lower(); this makes the two
        # modes agree.
        entries = sorted(p for p in folder_path.iterdir() if p.is_file())
        word_files = [p for p in entries if p.suffix.lower() in ('.doc', '.docx')]
        pdf_files = [p for p in entries if p.suffix.lower() == '.pdf']

        # Process Word files
        for word_file in word_files:
            success, message, output_path = self.convert_to_pdf(word_file, temp_dir)
            if success:
                results['converted_files'].append(output_path)
            else:
                results['failed_conversions'].append((word_file, message))

        # Check PDF files for password protection
        for pdf_file in pdf_files:
            is_protected, message = self.check_pdf_password_protected(pdf_file)
            if is_protected:
                results['password_protected'].append(pdf_file)
            else:
                results['pdf_files'].append(pdf_file)

        return results
