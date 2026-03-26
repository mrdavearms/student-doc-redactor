"""
Detection Service
Runs PII detection pipeline across documents.
Framework-agnostic — no Streamlit imports.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from src.core.pii_orchestrator import PIIOrchestrator
from src.core.pii_detector import PIIMatch
from src.core.text_extractor import TextExtractor


@dataclass
class DocumentPII:
    """PII detection results for a single document"""
    matches: List[PIIMatch] = field(default_factory=list)
    text_data: Dict = field(default_factory=dict)

    @property
    def match_count(self) -> int:
        return len(self.matches)


@dataclass
class DetectionResults:
    """PII detection results across all documents"""
    documents: List[Path] = field(default_factory=list)
    pii_by_document: Dict[Path, DocumentPII] = field(default_factory=dict)

    @property
    def total_matches(self) -> int:
        return sum(d.match_count for d in self.pii_by_document.values())


class DetectionService:
    """Runs PII detection across a set of PDF documents."""

    def __init__(
        self,
        student_name: str,
        parent_names: List[str] = None,
        family_names: List[str] = None,
        organisation_names: List[str] = None,
        require_ner: bool = False,
    ):
        self._orchestrator = PIIOrchestrator(
            student_name=student_name,
            parent_names=parent_names or [],
            family_names=family_names or [],
            organisation_names=organisation_names or [],
            require_ner=require_ner,
        )
        self._extractor = TextExtractor()

    def detect_all(self, pdf_paths: List[Path]) -> DetectionResults:
        """
        Extract text and detect PII in all provided PDFs.

        Args:
            pdf_paths: List of PDF file paths to scan

        Returns:
            DetectionResults with per-document PII data
        """
        results = DetectionResults(documents=list(pdf_paths))

        for pdf_path in pdf_paths:
            text_data = self._extractor.extract_text_from_pdf(pdf_path)

            pii_matches = []
            for page_num, page_data in text_data['pages'].items():
                matches = self._orchestrator.detect_pii_in_text(
                    page_data['text'], page_num
                )
                pii_matches.extend(matches)

            results.pii_by_document[pdf_path] = DocumentPII(
                matches=pii_matches,
                text_data=text_data,
            )

        return results
