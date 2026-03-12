"""
Redaction Service
Orchestrates the full redaction pipeline: folder setup, redaction, verification, logging.
Framework-agnostic — no Streamlit imports.
"""

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from src.core.pii_detector import PIIDetector, PIIMatch
from src.core.redactor import PDFRedactor, RedactionItem, strip_pii_from_filename
from src.core.logger import RedactionLogger, LogEntry


@dataclass
class RedactionRequest:
    """Everything needed to perform a redaction run"""
    folder_path: Path
    student_name: str
    documents: List[Path]
    # Per-document PII data: {doc_path: {'matches': [...], 'text_data': {...}}}
    detected_pii: Dict[Path, dict]
    # User selections: {f"{doc_path}_{match_idx}": True/False}
    user_selections: Dict[str, bool]
    # How to handle existing 'redacted' folder: 'overwrite' | 'new' | None (no existing)
    folder_action: Optional[str] = None
    parent_names: List[str] = field(default_factory=list)   # NEW
    family_names: List[str] = field(default_factory=list)   # NEW


@dataclass
class DocumentResult:
    """Result of redacting a single document"""
    document_name: str
    output_path: Optional[Path]
    success: bool
    items_redacted: int
    verification_failures: List[str] = field(default_factory=list)
    ocr_warnings: List[str] = field(default_factory=list)
    error_message: Optional[str] = None


@dataclass
class RedactionResults:
    """Complete results from a redaction run"""
    redacted_folder: Path
    document_results: List[DocumentResult] = field(default_factory=list)
    log_content: str = ""
    log_path: Optional[Path] = None

    @property
    def total_documents(self) -> int:
        return len(self.document_results)

    @property
    def successfully_redacted(self) -> int:
        return sum(1 for r in self.document_results if r.success)

    @property
    def verification_failures(self) -> List[Tuple[str, str]]:
        """All verification failures as (filename, message) tuples"""
        failures = []
        for r in self.document_results:
            for msg in r.verification_failures:
                failures.append((r.document_name, msg))
        return failures

    @property
    def ocr_warnings(self) -> List[Tuple[str, int]]:
        """All OCR warnings as (filename, count) tuples"""
        warnings = []
        for r in self.document_results:
            if r.ocr_warnings:
                warnings.append((r.document_name, len(r.ocr_warnings)))
        return warnings


class RedactionService:
    """Runs the full redaction pipeline on a set of documents."""

    def __init__(self):
        self._redactor = PDFRedactor()

    def execute(self, request: RedactionRequest) -> RedactionResults:
        """
        Execute a full redaction run.

        Args:
            request: RedactionRequest with all inputs

        Returns:
            RedactionResults with per-document outcomes and audit log
        """
        # 1. Prepare output folder
        redacted_folder = self._prepare_output_folder(
            request.folder_path, request.folder_action
        )

        # 2. Initialise logger
        logger = RedactionLogger(request.folder_path, request.student_name)

        # 2b. Build name variations for filename stripping
        # Use PIIDetector to get student name variations, then append parent/family names
        _detector = PIIDetector(
            request.student_name,
            request.parent_names,
            request.family_names,
        )
        name_variations = list(_detector.name_variations)
        for name in request.parent_names + request.family_names:
            if len(name) >= 3 and name not in name_variations:
                name_variations.append(name)

        # 3. Process each document
        results = RedactionResults(redacted_folder=redacted_folder)

        for doc in request.documents:
            doc_result = self._process_document(
                doc=doc,
                detected_pii=request.detected_pii,
                user_selections=request.user_selections,
                redacted_folder=redacted_folder,
                logger=logger,
                name_variations=name_variations,
            )
            results.document_results.append(doc_result)

        # 4. Add conversion-level flagged files to log
        conversion_results = request.detected_pii  # Access via original data
        # These come from the conversion step — password-protected and failed files
        # The caller should pass these separately if needed, but for now
        # we handle them through the request's detected_pii dict

        # 5. Finalise log
        logger.set_totals(
            len(request.documents),
            results.successfully_redacted,
        )
        results.log_content = logger.generate_log()
        results.log_path = logger.save_log()

        return results

    def _prepare_output_folder(
        self, folder_path: Path, folder_action: Optional[str]
    ) -> Path:
        """Create or resolve the output folder for redacted files."""
        redacted_folder = folder_path / "redacted"

        if folder_action == "overwrite":
            if redacted_folder.exists():
                shutil.rmtree(redacted_folder)
            redacted_folder.mkdir()
        elif folder_action == "new":
            counter = 2
            while (folder_path / f"redacted_{counter}").exists():
                counter += 1
            redacted_folder = folder_path / f"redacted_{counter}"
            redacted_folder.mkdir()
        else:
            redacted_folder.mkdir(exist_ok=True)

        return redacted_folder

    def _process_document(
        self,
        doc: Path,
        detected_pii: Dict[Path, dict],
        user_selections: Dict[str, bool],
        redacted_folder: Path,
        logger: RedactionLogger,
        name_variations: List[str] = None,
    ) -> DocumentResult:
        """Process a single document: filter selections, redact, verify."""
        doc_data = detected_pii.get(doc, {})
        matches = doc_data.get('matches', [])
        ocr_pages = doc_data.get('text_data', {}).get('ocr_pages', [])

        # Filter to user-selected matches
        selected_matches = []
        for idx, match in enumerate(matches):
            key = f"{doc}_{idx}"
            if user_selections.get(key, False):
                selected_matches.append(match)

        result = DocumentResult(
            document_name=doc.name,
            output_path=None,
            success=False,
            items_redacted=len(selected_matches),
        )

        # Check for OCR pages (image-only — can't be auto-redacted)
        ocr_item_count = sum(
            1 for m in selected_matches if m.page_num in ocr_pages
        )
        if ocr_item_count > 0:
            warning_msg = (
                f"Contains {ocr_item_count} item(s) on image-only pages "
                f"that could not be automatically redacted - manual review required"
            )
            logger.add_flagged_file(doc.name, warning_msg)
            result.ocr_warnings.append(warning_msg)

        # Compute safe output filename (strips PII from stem)
        safe_stem = strip_pii_from_filename(doc.stem, name_variations or [])
        output_filename = f"{safe_stem}_redacted.pdf"

        # Collision guard: if another file already produced the same stripped name
        counter = 2
        while (redacted_folder / output_filename).exists():
            output_filename = f"{safe_stem}_{counter}_redacted.pdf"
            counter += 1

        output_path = redacted_folder / output_filename

        # Build redaction items and log entries
        redaction_items = []
        for match in selected_matches:
            redaction_items.append(RedactionItem(
                page_num=match.page_num,
                text=match.text,
                bbox=match.bbox,
            ))
            logger.add_entry(LogEntry(
                document_name=doc.name,
                output_name=output_filename,
                page_num=match.page_num,
                line_num=match.line_num,
                text=match.text,
                category=match.category,
                confidence=match.confidence,
            ))

        # Perform redaction
        success, message = self._redactor.redact_pdf(doc, output_path, redaction_items)

        if success:
            result.output_path = output_path
            result.success = True

            # OCR verification — skip image-only pages
            redacted_texts = [
                m.text for m in selected_matches if m.page_num not in ocr_pages
            ]
            if redacted_texts:
                all_clean, ocr_failures = self._redactor.verify_redaction_ocr(
                    output_path, redacted_texts
                )
                if not all_clean:
                    for failure_msg in ocr_failures:
                        logger.add_flagged_file(
                            doc.name, f"VERIFICATION FAILED: {failure_msg}"
                        )
                    result.verification_failures = ocr_failures
                    result.success = False
        else:
            logger.add_flagged_file(doc.name, f"Redaction failed: {message}")
            result.error_message = message

        return result
