"""
Detection Service
Runs PII detection pipeline across documents.
Framework-agnostic — no Streamlit imports.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

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
    # Only the documents that were scanned. A document that could not be read
    # is listed in failed_documents instead, so the caller can show it — a
    # dropped document must never be silent.
    documents: List[Path] = field(default_factory=list)
    pii_by_document: Dict[Path, DocumentPII] = field(default_factory=dict)
    failed_documents: List[Tuple[Path, str]] = field(default_factory=list)

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
            DetectionResults with per-document PII data. A document that
            fails to extract or scan does not abort the run: it goes into
            failed_documents with the reason, and is left out of documents.
        """
        results = DetectionResults()

        for pdf_path in pdf_paths:
            try:
                text_data = self._extractor.extract_text_from_pdf(pdf_path)

                pii_matches = []
                for page_num, page_data in text_data['pages'].items():
                    # Text OCR'd from images embedded in a native page is
                    # scanned after the page's own text, so a name that only
                    # exists inside a pasted screenshot is still offered.
                    text = page_data['text']
                    image_text = page_data.get('image_text', '')
                    if image_text:
                        text = text.rstrip() + '\n' + image_text
                    matches = self._orchestrator.detect_pii_in_text(
                        text, page_num
                    )
                    pii_matches.extend(matches)
            except Exception as e:
                results.failed_documents.append((pdf_path, str(e)))
                continue

            results.documents.append(pdf_path)
            results.pii_by_document[pdf_path] = DocumentPII(
                matches=pii_matches,
                text_data=text_data,
            )

        return results

    def detect_in_text(self, text: str) -> List['PIIMatch']:
        """
        Detect PII in a block of text with no document behind it.

        The orchestrator is already pure text-in; this exists so callers do not
        reach into the private _orchestrator attribute.
        """
        return self._orchestrator.detect_pii_in_text(text, 1)
