"""
Conversion Service
Handles dependency checking and document conversion (Word -> PDF).
Framework-agnostic — no Streamlit imports.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

from src.core.document_converter import DocumentConverter
from src.core.text_extractor import TextExtractor


@dataclass
class DependencyStatus:
    """Status of external dependencies"""
    libreoffice_ok: bool
    libreoffice_message: str
    tesseract_ok: bool

    @property
    def can_convert_word(self) -> bool:
        return self.libreoffice_ok


@dataclass
class ConversionResults:
    """Results from processing a folder of documents"""
    pdf_files: List[Path] = field(default_factory=list)
    converted_files: List[Path] = field(default_factory=list)
    failed_conversions: List[Tuple[Path, str]] = field(default_factory=list)
    password_protected: List[Path] = field(default_factory=list)

    @property
    def total_files(self) -> int:
        return (
            len(self.pdf_files)
            + len(self.converted_files)
            + len(self.failed_conversions)
            + len(self.password_protected)
        )

    @property
    def processable_count(self) -> int:
        return len(self.pdf_files) + len(self.converted_files)

    @property
    def flagged_count(self) -> int:
        return len(self.failed_conversions) + len(self.password_protected)

    @property
    def all_processable_pdfs(self) -> List[Path]:
        return self.pdf_files + self.converted_files


class ConversionService:
    """Checks dependencies and converts documents in a folder."""

    def __init__(self):
        self._converter = DocumentConverter()
        self._extractor = TextExtractor()

    def check_dependencies(self) -> DependencyStatus:
        """Check all external dependencies and return their status."""
        lo_ok, lo_msg = self._converter.check_libreoffice_installed()
        tess_ok = self._extractor.tesseract_available

        return DependencyStatus(
            libreoffice_ok=lo_ok,
            libreoffice_message=lo_msg,
            tesseract_ok=tess_ok,
        )

    def process_folder(self, folder_path: Path) -> ConversionResults:
        """
        Process all documents in a folder: convert Word files, check PDFs.

        Args:
            folder_path: Path to the folder containing documents

        Returns:
            ConversionResults with categorised file lists
        """
        raw = self._converter.process_folder(folder_path)

        return ConversionResults(
            pdf_files=raw['pdf_files'],
            converted_files=raw['converted_files'],
            failed_conversions=raw['failed_conversions'],
            password_protected=raw['password_protected'],
        )
