"""
binary_resolver.py

Resolves paths to external binaries (Tesseract, LibreOffice) for both
development (system install) and production (bundled inside app) environments.

In production, main.cjs sets RESOURCES_PATH to process.resourcesPath before
spawning the Python backend. All resolution checks bundled paths first.
"""

import os
import platform
from pathlib import Path


def _resources_path() -> Path | None:
    """Return the bundled resources directory, or None in dev mode."""
    resources = os.environ.get("RESOURCES_PATH")
    if resources:
        p = Path(resources)
        if p.exists():
            return p
    return None


def resolve_tesseract() -> str | None:
    """
    Return the absolute path to the Tesseract binary, or None if not found.

    Checks bundled path first (production), then system paths (dev).
    """
    resources = _resources_path()
    if resources:
        if platform.system() == "Windows":
            candidate = resources / "tesseract" / "tesseract.exe"
        else:
            candidate = resources / "tesseract"
        if candidate.exists():
            return str(candidate)

    system = platform.system()
    if system == "Darwin":
        candidates = [
            "/opt/homebrew/bin/tesseract",   # Apple Silicon Homebrew
            "/usr/local/bin/tesseract",       # Intel Mac Homebrew
        ]
    elif system == "Windows":
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
    else:
        candidates = ["/usr/bin/tesseract", "/usr/local/bin/tesseract"]

    for path in candidates:
        if Path(path).exists():
            return path

    return None


def resolve_tessdata() -> str | None:
    """
    Return the absolute path to the tessdata directory, or None if not found.
    Used to set TESSDATA_PREFIX so Tesseract finds its language data.
    """
    resources = _resources_path()
    if resources:
        candidate = resources / "tessdata"
        if candidate.exists():
            return str(candidate)
    return None


def resolve_libreoffice() -> str | None:
    """
    Return the absolute path to the soffice binary, or None if not found.
    LibreOffice is NOT bundled — this discovers a user's existing install.
    """
    system = platform.system()

    if system == "Darwin":
        candidates = [
            "/opt/homebrew/bin/soffice",
            "/usr/local/bin/soffice",
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        ]
    elif system == "Windows":
        candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
    else:
        candidates = ["/usr/bin/soffice", "/usr/local/bin/soffice"]

    for path in candidates:
        if Path(path).exists():
            return path

    return None
