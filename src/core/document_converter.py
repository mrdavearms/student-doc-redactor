"""
Document Converter
Converts Word documents to PDF using LibreOffice in headless mode.
"""

import atexit
import os
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


def _temp_root() -> Path:
    """This backend process's private temp directory, created on first use."""
    global _TEMP_ROOT
    if _TEMP_ROOT is None:
        # Electron creates (and, after this process exits, deletes) the folder
        # and passes it in. The atexit below stays: it covers a manual uvicorn
        # run, and removing an already-removed folder is harmless. The
        # fallback has its own prefix so Electron's launch sweep never removes
        # the folder of a manual uvicorn or pytest run that is still going.
        given = os.environ.get("REDACTION_TEMP_ROOT")
        if given and os.path.isabs(given) and os.path.isdir(given):
            _TEMP_ROOT = Path(given)
        else:
            _TEMP_ROOT = Path(tempfile.mkdtemp(prefix="redaction-tool-py-"))
        atexit.register(shutil.rmtree, _TEMP_ROOT, True)
    return _TEMP_ROOT


def _profile_dir() -> Path:
    """
    A LibreOffice user profile private to this process.

    Without -env:UserInstallation, soffice hands a headless job to any
    LibreOffice window the user already has open and exits 0 with whatever
    that window did. A good document still converts that way (verified on
    LibreOffice 26.8), but a damaged one exits 0 with no PDF and NO error
    text, so the user saw "Conversion failed:" and nothing after it. With its
    own profile the job runs in its own process and reports its own error.

    The profile is locked (see _write_locked_profile) before it is handed to
    soffice, every time: rewriting a few hundred bytes is cheaper than
    trusting that LibreOffice left the file as we wrote it.
    """
    profile = _temp_root() / "lo-profile"
    _write_locked_profile(profile)
    return profile


# (configuration path, property, value). Paths are from the
# installed schema (/Applications/LibreOffice.app/Contents/Resources/registry/
# main.xcd, LibreOffice 26.8); see _write_locked_profile for what each does.
_LOCKED_SETTINGS = (
    ("/org.openoffice.Office.Common/Security/Scripting", "DisableMacrosExecution", "true"),
    ("/org.openoffice.Office.Common/Security/Scripting", "MacroSecurityLevel", "3"),
    ("/org.openoffice.Office.Common/Security/Scripting", "BlockUntrustedRefererLinks", "true"),
    ("/org.openoffice.Office.Common/Security/Scripting", "DisableActiveContent", "true"),
    ("/org.openoffice.Office.Writer/Content/Update", "Link", "0"),
)


def _write_locked_profile(profile: Path) -> None:
    """
    Write profile/user/registrymodifications.xcu so LibreOffice opens a
    third-party Word file with macros, active content and remote links off.

    The documents come from outside the school (clinicians, other schools),
    and the app's promise is that nothing leaves the machine. A fresh profile
    has LibreOffice's ordinary defaults, which were chosen for a person
    opening their own files, not for a converter.

    - /org.openoffice.Office.Common/Security/Scripting/DisableMacrosExecution
      = true. No Basic, BeanShell, JavaScript or Python macro runs at all;
      the schema says MacroSecurityLevel is then ignored.
    - /org.openoffice.Office.Common/Security/Scripting/MacroSecurityLevel
      = 3 ("very high": only macros from trusted locations, and the profile
      lists none). Belt and braces in case the first setting is ever dropped.
    - /org.openoffice.Office.Common/Security/Scripting/BlockUntrustedRefererLinks
      = true. Blocks links (linked images, remote templates and the like) that
      originate from a document outside the trusted locations; the profile
      lists none, so every document's links are blocked.
    - /org.openoffice.Office.Common/Security/Scripting/DisableActiveContent
      = true. Disables embedded OLE objects and DDE links.
    - /org.openoffice.Office.Writer/Content/Update/Link = 0, the value
      LibreOffice's source code documents as "never" (its LinkUpdateMode
      enum: NEVER=0, MANUAL=1, AUTOMATIC=2). The schema itself gives no
      numeric mapping (default 1, "Always/On request/Never"), and the mapping
      is NOT observable in headless conversion: on LibreOffice 26.8 a section
      linked to a local file kept its cached text with this set to 0, 1 or 2,
      and even with the document's own LinkUpdateMode set to "always".
      Kept as defence in depth. Word files open in Writer.

    Not set: /org.openoffice.Office.Calc/Content/Update/Link, because a Word
    file never opens in Calc. No separate "load external graphics" setting
    exists in the schema; BlockUntrustedRefererLinks is what covers that.

    Measured on LibreOffice 26.8 (25 Oct 2026): a .docx with an externally
    linked picture and a remote attached template made no request during a
    headless conversion even WITHOUT these settings. The lock is defence in
    depth against other versions and other link types, and
    tests/test_document_converter.py::test_no_remote_fetch_from_linked_image
    guards the behaviour.
    """
    items = "".join(
        f'<item oor:path="{path}"><prop oor:name="{name}" oor:op="fuse">'
        f'<value>{value}</value></prop></item>\n'
        for path, name, value in _LOCKED_SETTINGS
    )
    xcu = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<oor:items xmlns:oor="http://openoffice.org/2001/registry" '
        'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
        f'{items}'
        '</oor:items>\n'
    )
    user = profile / "user"
    user.mkdir(parents=True, exist_ok=True)
    (user / "registrymodifications.xcu").write_text(xcu, encoding="utf-8")


def _conversion_dir() -> Path:
    """
    An empty directory for this conversion run's PDFs, outside the user's
    folder.

    Cleared on each call: one conversion run supersedes the previous one, which
    is what the old in-folder behaviour did anyway by overwriting the same
    filenames.
    """
    converted = _temp_root() / "converted"
    shutil.rmtree(converted, ignore_errors=True)
    converted.mkdir(parents=True, exist_ok=True)
    return converted


def clear_conversions() -> None:
    """
    Delete this process's converted (unredacted) PDFs now, e.g. when the user
    starts over. Does nothing if no conversion has ever run: it must not create
    a temp root just to empty it.
    """
    if _TEMP_ROOT is not None:
        shutil.rmtree(_TEMP_ROOT / "converted", ignore_errors=True)


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
                    f'-env:UserInstallation={_profile_dir().as_uri()}',
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
                error_msg = (result.stderr or result.stdout or '').strip()
                if not error_msg:
                    error_msg = ("LibreOffice produced no PDF and gave no reason. "
                                 "The file may be damaged or not a Word document.")
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
        # "~$Report.docx" is the lock file Word keeps beside an open document,
        # on both platforms; it is not a document and LibreOffice cannot open it.
        entries = sorted(p for p in folder_path.iterdir()
                         if p.is_file() and not p.name.startswith('~$'))
        word_files = [p for p in entries if p.suffix.lower() in ('.doc', '.docx')]
        pdf_files = [p for p in entries if p.suffix.lower() == '.pdf']

        # Process Word files. Each conversion gets its own sub-folder:
        # LibreOffice names the output after the source stem, so "Report.doc"
        # and "Report.docx" in one folder both produced converted/Report.pdf and
        # the second silently overwrote the first — one document never reached
        # detection, and nothing said so.
        for index, word_file in enumerate(word_files, start=1):
            out_dir = temp_dir / f"{index:03d}"
            out_dir.mkdir(parents=True, exist_ok=True)
            success, message, output_path = self.convert_to_pdf(word_file, out_dir)
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
