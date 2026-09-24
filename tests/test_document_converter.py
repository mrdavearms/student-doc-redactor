"""
LibreOffice is run with a profile private to this process.

Without -env:UserInstallation, soffice hands the headless job to any
LibreOffice window the user has open. A good document still converts, but a
damaged one then exits 0 with no PDF and no error text at all (reproduced on
LibreOffice 26.8), so the user saw "Conversion failed:" and nothing after it.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import document_converter
from document_converter import DocumentConverter


def _converter():
    with patch('binary_resolver.resolve_libreoffice', return_value='/fake/soffice'):
        conv = DocumentConverter()
    conv.soffice_path = '/fake/soffice'
    return conv


def _run_recording(calls, returncode=0, stdout='', stderr=''):
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    return fake_run


class TestPrivateProfile:

    def test_soffice_gets_a_profile_under_the_temp_root_not_the_users_folder(self, tmp_path):
        calls = []
        docx = tmp_path / "docs" / "Billy Bob report.docx"
        docx.parent.mkdir()
        with patch('document_converter.subprocess.run', _run_recording(calls)):
            _converter().convert_to_pdf(docx, tmp_path / "out")

        cmd = calls[0]
        env_args = [a for a in cmd if a.startswith('-env:UserInstallation=')]
        assert len(env_args) == 1, cmd
        uri = env_args[0].split('=', 1)[1]
        assert uri.startswith('file://')
        profile = Path(uri[len('file://'):])
        assert profile.is_relative_to(document_converter._temp_root())
        assert not profile.is_relative_to(tmp_path)
        # Before the mode flags, where soffice expects bootstrap variables.
        assert cmd.index(env_args[0]) < cmd.index('--headless')


class TestFailureMessages:

    def test_exit_zero_with_no_pdf_and_no_output_still_explains_itself(self, tmp_path):
        docx = tmp_path / "Damaged report.docx"
        with patch('document_converter.subprocess.run', _run_recording([], 0, '', '')):
            ok, message, path = _converter().convert_to_pdf(docx, tmp_path / "out")
        assert not ok
        assert path is None
        assert message.startswith("Conversion failed: ")
        assert len(message) > len("Conversion failed: ")
        assert "no PDF" in message

    def test_libreoffice_error_text_is_passed_through(self, tmp_path):
        docx = tmp_path / "Damaged report.docx"
        with patch('document_converter.subprocess.run',
                   _run_recording([], 1, '', 'Error: source file could not be loaded\n')):
            ok, message, _ = _converter().convert_to_pdf(docx, tmp_path / "out")
        assert not ok
        assert message == "Conversion failed: Error: source file could not be loaded"
