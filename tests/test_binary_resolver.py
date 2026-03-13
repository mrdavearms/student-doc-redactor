import sys
import os
sys.path.insert(0, 'src/core')

import pytest
from unittest.mock import patch
from pathlib import Path


def test_resolve_tesseract_returns_string_or_none():
    from binary_resolver import resolve_tesseract
    result = resolve_tesseract()
    assert result is None or isinstance(result, str)


def test_resolve_libreoffice_returns_string_or_none():
    from binary_resolver import resolve_libreoffice
    result = resolve_libreoffice()
    assert result is None or isinstance(result, str)


def test_resolve_tesseract_uses_resources_path_when_set(tmp_path):
    from binary_resolver import resolve_tesseract
    # Simulate production: RESOURCES_PATH env var pointing to a temp dir
    (tmp_path / "bundled-tesseract").mkdir()
    fake_binary = tmp_path / "bundled-tesseract" / "tesseract"
    fake_binary.touch()
    with patch.dict(os.environ, {"RESOURCES_PATH": str(tmp_path)}):
        with patch("platform.system", return_value="Darwin"):
            result = resolve_tesseract()
    assert result == str(fake_binary)


def test_resolve_libreoffice_windows_paths(tmp_path):
    from binary_resolver import resolve_libreoffice
    # At minimum, function should not raise on Windows
    with patch("platform.system", return_value="Windows"):
        result = resolve_libreoffice()
    assert result is None or isinstance(result, str)


def test_resolve_tessdata_returns_string_or_none():
    from binary_resolver import resolve_tessdata
    result = resolve_tessdata()
    assert result is None or isinstance(result, str)


def test_resolve_tessdata_uses_resources_path_when_set(tmp_path):
    from binary_resolver import resolve_tessdata
    (tmp_path / "bundled-tesseract").mkdir()
    fake_tessdata = tmp_path / "bundled-tesseract" / "tessdata"
    fake_tessdata.mkdir()
    with patch.dict(os.environ, {"RESOURCES_PATH": str(tmp_path)}):
        result = resolve_tessdata()
    assert result == str(fake_tessdata)
