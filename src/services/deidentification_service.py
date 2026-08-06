"""
De-identification Service
Orchestrates the "de-identify for AI" pathway: replace PII in the extracted
document text with non-identifying labels and write plain-text output.

Framework-agnostic — no Streamlit imports.

Differs from redaction in what leaves the machine. The output here is meant to
be pasted into an AI tool, so nothing in the output folder may re-identify
anyone: the key file is written next to the ORIGINALS instead, and the audit
log records labels rather than the names they replaced.
"""

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePath
from typing import Dict, List, Optional, Set, Tuple

import fitz  # PyMuPDF

from src.core.logger import RedactionLogger, LogEntry
from src.core.pseudonym_map import PseudonymMap, is_person_category
from src.core.redactor import (
    FOOTER_ZONE_FRACTION,
    HEADER_ZONE_FRACTION,
    is_same_file,
    strip_pii_from_filename,
)
from src.core.text_deidentifier import (
    deidentify_text,
    fuzzy_leftovers,
    verify_deidentified,
)


# The warning lives in the FILENAME because the likeliest accident is a user
# dragging a whole folder into an AI chat, not reading a header first.
KEY_FILE_NAME = "DO-NOT-UPLOAD-name-key.txt"
LOG_FILE_NAME = "deidentification_log.txt"

# The audit log's header takes a student name. In this mode it takes the label.
LOG_STUDENT_PLACEHOLDER = "[Student]"

_PAGE_MARKER = "--- Page {} ---"


@dataclass
class DeidentifyRequest:
    """Everything needed to perform a de-identification run."""
    folder_path: Path
    student_name: str
    documents: List[Path]
    detected_pii: Dict[Path, dict]
    user_selections: Dict[str, bool]
    folder_action: Optional[str] = None
    custom_output_path: Optional[Path] = None
    custom_output_filename: Optional[str] = None
    parent_names: List[str] = field(default_factory=list)
    family_names: List[str] = field(default_factory=list)
    organisation_names: List[str] = field(default_factory=list)
    # Reinterpreted for this mode: drop header/footer-zone text from the output
    # rather than blanking those zones in a PDF.
    redact_header_footer: bool = False


@dataclass
class DeidentifyDocumentResult:
    """Result of de-identifying a single document."""
    document_name: str
    output_path: Optional[Path]
    success: bool
    items_replaced: int
    verification_failures: List[str] = field(default_factory=list)
    ocr_warnings: List[str] = field(default_factory=list)
    image_warnings: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    quarantine_path: Optional[Path] = None


@dataclass
class DeidentifyResults:
    """Complete results from a de-identification run."""
    output_folder: Path
    key_file_path: Optional[Path] = None
    document_results: List[DeidentifyDocumentResult] = field(default_factory=list)
    log_content: str = ""
    log_path: Optional[Path] = None
    cancelled: bool = False
    requested_document_count: Optional[int] = None

    @property
    def total_documents(self) -> int:
        if self.requested_document_count is not None:
            return self.requested_document_count
        return len(self.document_results)

    @property
    def successfully_deidentified(self) -> int:
        return sum(1 for r in self.document_results if r.success)

    @property
    def verification_failures(self) -> List[Tuple[str, str]]:
        return [(r.document_name, msg)
                for r in self.document_results
                for msg in r.verification_failures]

    @property
    def ocr_warnings(self) -> List[Tuple[str, int]]:
        return [(r.document_name, len(r.ocr_warnings))
                for r in self.document_results if r.ocr_warnings]


class DeidentificationService:
    """Runs the de-identification pipeline over a set of documents."""

    def execute(self, request: DeidentifyRequest, should_cancel=None) -> DeidentifyResults:
        output_folder = self._prepare_output_folder(
            request.folder_path, request.folder_action, request.custom_output_path
        )

        # The log header would otherwise carry the real student name.
        logger = RedactionLogger(request.folder_path, LOG_STUDENT_PLACEHOLDER)

        pmap = PseudonymMap(
            student_name=request.student_name,
            parent_names=request.parent_names,
            family_names=request.family_names,
            organisation_names=request.organisation_names,
        )

        # Register every discovered person up front so labels are consistent
        # across all documents in the run — the same teacher must not be
        # [Person 2] in one file and [Person 5] in the next.
        selected_by_doc = {
            doc: self._selected_matches(doc, request.detected_pii, request.user_selections)
            for doc in request.documents
        }
        for doc in request.documents:
            for match in selected_by_doc[doc]:
                if is_person_category(getattr(match, 'category', '')):
                    pmap.register_person(match.text)

        filename_override = None
        if request.custom_output_filename and len(request.documents) == 1:
            filename_override = self._sanitise_output_filename(
                request.custom_output_filename
            )

        results = DeidentifyResults(
            output_folder=output_folder,
            requested_document_count=len(request.documents),
        )

        name_variations = self._filename_variations(request)

        for doc in request.documents:
            if should_cancel is not None and should_cancel():
                results.cancelled = True
                break
            results.document_results.append(self._process_document(
                doc=doc,
                selected_matches=selected_by_doc[doc],
                text_data=request.detected_pii.get(doc, {}).get('text_data', {}),
                pmap=pmap,
                output_folder=output_folder,
                logger=logger,
                name_variations=name_variations,
                drop_header_footer=request.redact_header_footer,
                output_filename_override=filename_override,
            ))

        # The key file goes next to the ORIGINALS, never into the output folder:
        # the originals are already sensitive, so it adds no new exposure there,
        # and it leaves every file in the output folder safe to upload.
        results.key_file_path = self._write_key_file(request.folder_path, pmap)

        logger.set_totals(len(request.documents), results.successfully_deidentified)
        if results.cancelled:
            logger.set_cancelled(True)
        results.log_content = logger.generate_log()
        results.log_path = logger.save_log(LOG_FILE_NAME)

        return results

    # ── Setup helpers ────────────────────────────────────────────────────

    @staticmethod
    def _selected_matches(doc: Path, detected_pii: Dict, user_selections: Dict) -> List:
        matches = detected_pii.get(doc, {}).get('matches', [])
        return [m for idx, m in enumerate(matches)
                if user_selections.get(f"{doc}_{idx}", False)]

    @staticmethod
    def _filename_variations(request: DeidentifyRequest) -> List[str]:
        """Name strings used to strip PII out of output filenames."""
        variations: List[str] = []
        for name in ([request.student_name] + list(request.parent_names)
                     + list(request.family_names)):
            if name and name.strip():
                variations.append(name.strip())
                variations.extend(p for p in name.split() if len(p) >= 3)
        for org in request.organisation_names:
            if org and org.strip():
                variations.append(org.strip())
                variations.extend(w for w in org.split() if len(w) >= 3)
        return list(dict.fromkeys(variations))

    @staticmethod
    def _sanitise_output_filename(name: str) -> Optional[str]:
        """
        Reduce a user-supplied filename to a bare, safe .txt filename. Strips
        any directory component so a crafted name cannot write outside the
        chosen folder.
        """
        bare = PurePath(name.replace("\\", "/")).name.strip()
        if not bare or bare in (".", ".."):
            return None
        if not bare.lower().endswith(".txt"):
            bare = f"{PurePath(bare).stem}.txt"
        return bare

    def _prepare_output_folder(
        self, folder_path: Path, folder_action: Optional[str],
        custom_output_path: Optional[Path] = None,
    ) -> Path:
        if custom_output_path:
            custom_output_path.mkdir(parents=True, exist_ok=True)
            return custom_output_path

        output_folder = folder_path / "deidentified"

        if folder_action == "overwrite":
            if output_folder.exists():
                shutil.rmtree(output_folder)
            output_folder.mkdir()
        elif folder_action == "new":
            counter = 2
            while (folder_path / f"deidentified_{counter}").exists():
                counter += 1
            output_folder = folder_path / f"deidentified_{counter}"
            output_folder.mkdir()
        else:
            output_folder.mkdir(exist_ok=True)

        return output_folder

    # ── Text assembly ────────────────────────────────────────────────────

    @staticmethod
    def _zone_lines(doc_path: Path) -> Dict[int, Set[str]]:
        """
        Text lines sitting in each page's header/footer zone.

        Returned as literal strings to drop rather than coordinates, so the
        caller keeps using the same extracted text detection ran against —
        including AcroForm widget values, which have no page geometry.

        Image-only pages yield nothing here: their text came from OCR, which
        carries no block geometry. Those pages keep their header/footer text,
        and the caller reports that.
        """
        zones: Dict[int, Set[str]] = {}
        try:
            with fitz.open(str(doc_path)) as pdf:
                for page_index in range(len(pdf)):
                    page = pdf[page_index]
                    height = page.rect.height
                    header_y = height * HEADER_ZONE_FRACTION
                    footer_y = height * (1 - FOOTER_ZONE_FRACTION)
                    drop: Set[str] = set()
                    for block in page.get_text("blocks"):
                        x0, y0, x1, y1, text = block[0], block[1], block[2], block[3], block[4]
                        if len(block) > 6 and block[6] != 0:
                            continue
                        if y1 <= header_y or y0 >= footer_y:
                            for line in str(text).splitlines():
                                stripped = line.strip()
                                if stripped:
                                    drop.add(stripped)
                    if drop:
                        zones[page_index + 1] = drop
        except Exception:
            return {}
        return zones

    @staticmethod
    def _count_embedded_images(doc_path: Path, native_pages: Set[int]) -> int:
        """
        Raster images embedded in text-layer pages.

        Their content never reaches the text output — which is protective, but
        also silent information loss the user should be told about. Image-only
        (scanned) pages are excluded: there the page IS the image and its text
        did come through, via OCR.
        """
        total = 0
        try:
            with fitz.open(str(doc_path)) as pdf:
                for page_index in range(len(pdf)):
                    if (page_index + 1) not in native_pages:
                        continue
                    total += len(pdf[page_index].get_images(full=True))
        except Exception:
            return 0
        return total

    @staticmethod
    def _page_text(raw_text: str, drop_lines: Optional[Set[str]]) -> str:
        if not drop_lines:
            return raw_text
        kept = [line for line in raw_text.splitlines()
                if line.strip() not in drop_lines]
        return "\n".join(kept)

    # ── Per-document processing ──────────────────────────────────────────

    def _process_document(
        self,
        doc: Path,
        selected_matches: List,
        text_data: Dict,
        pmap: PseudonymMap,
        output_folder: Path,
        logger: RedactionLogger,
        name_variations: List[str],
        drop_header_footer: bool,
        output_filename_override: Optional[str],
    ) -> DeidentifyDocumentResult:
        result = DeidentifyDocumentResult(
            document_name=doc.name,
            output_path=None,
            success=False,
            items_replaced=0,
        )

        pages = text_data.get('pages') or {}
        if not pages:
            result.error_message = (
                "No extracted text available for this document. Run detection again."
            )
            logger.add_flagged_file(doc.name, result.error_message)
            return result

        ocr_pages = set(text_data.get('ocr_pages', []))
        native_pages = {n for n in pages if n not in ocr_pages}

        if output_filename_override:
            output_filename = output_filename_override
        else:
            safe_stem = strip_pii_from_filename(doc.stem, name_variations or [])
            output_filename = f"{safe_stem}_deidentified.txt"
            counter = 2
            while (output_folder / output_filename).exists():
                output_filename = f"{safe_stem}_{counter}_deidentified.txt"
                counter += 1

        output_path = output_folder / output_filename

        if is_same_file(output_path, doc):
            message = (
                "Cannot save the de-identified copy over the original document. "
                "Choose a different filename or folder."
            )
            logger.add_flagged_file(doc.name, message)
            result.error_message = message
            return result

        zones = self._zone_lines(doc) if drop_header_footer else {}

        # Replace page by page so OCR-sourced output can be verified separately.
        # Every selected match is applied to every page: a name detected on page
        # one must also go from page five.
        page_outputs: Dict[int, str] = {}
        total_replacements = 0
        for page_num in sorted(pages):
            raw = self._page_text(
                pages[page_num].get('text', '') or '', zones.get(page_num)
            )
            cleaned, count = deidentify_text(raw, selected_matches, pmap)
            page_outputs[page_num] = cleaned
            total_replacements += count

        result.items_replaced = total_replacements

        if ocr_pages:
            result.ocr_warnings.append(
                f"{len(ocr_pages)} page(s) were read by OCR (scanned). "
                f"Check the text is complete and correct."
            )
            if drop_header_footer and ocr_pages:
                result.ocr_warnings.append(
                    f"Header/footer removal could not be applied to "
                    f"{len(ocr_pages)} scanned page(s) — review them for letterheads."
                )

        image_count = self._count_embedded_images(doc, native_pages)
        if image_count:
            result.image_warnings.append(
                f"{image_count} image(s) were not included in the text output. "
                f"Any information inside them is absent, not de-identified."
            )

        # Verify before writing. Exact check everywhere; the fuzzy check only on
        # OCR text, where a misread name would otherwise ship readable.
        selected_texts = list({m.text.strip() for m in selected_matches
                               if (m.text or '').strip()})
        labels = pmap.all_labels()
        full_output = "\n\n".join(
            f"{_PAGE_MARKER.format(n)}\n\n{page_outputs[n]}"
            for n in sorted(page_outputs)
        )

        leftovers = verify_deidentified(full_output, selected_texts, labels)
        for page_num in sorted(ocr_pages & set(page_outputs)):
            for item in fuzzy_leftovers(page_outputs[page_num], selected_texts, labels):
                if item not in leftovers:
                    leftovers.append(item)

        for match in selected_matches:
            logger.add_entry(LogEntry(
                document_name=doc.name,
                output_name=output_filename,
                page_num=match.page_num,
                line_num=match.line_num,
                # The LABEL, never the real value: this log sits alongside the
                # documents and must not become a second copy of the key file.
                text=pmap.label_for(match.text, match.category),
                category=match.category,
                confidence=match.confidence,
            ))

        if leftovers:
            quarantine = output_folder / f"{PurePath(output_filename).stem}.UNVERIFIED.txt"
            self._write_text(quarantine, full_output, doc.name)
            result.quarantine_path = quarantine
            result.verification_failures = [
                f"Possible remaining reference to \"{item}\"" for item in leftovers
            ]
            logger.add_flagged_file(
                doc.name,
                f"Verification found {len(leftovers)} possible remaining reference(s); "
                f"saved as {quarantine.name} for manual review",
            )
            return result

        try:
            self._write_text(output_path, full_output, doc.name)
        except Exception as e:
            result.error_message = f"Could not write output file: {e}"
            logger.add_flagged_file(doc.name, result.error_message)
            return result

        result.output_path = output_path
        result.success = True
        return result

    @staticmethod
    def _write_text(path: Path, body: str, source_name: str) -> None:
        header = (
            f"De-identified copy of: {source_name}\n"
            f"Names and personal details have been replaced with labels such as "
            f"[Student] and [Parent 1].\n"
            f"{'=' * 70}\n\n"
        )
        path.write_text(header + body, encoding='utf-8')

    # ── Key file ─────────────────────────────────────────────────────────

    @staticmethod
    def _write_key_file(folder_path: Path, pmap: PseudonymMap) -> Optional[Path]:
        entries = pmap.key_entries()
        if not entries:
            return None

        lines = [
            "DO NOT UPLOAD THIS FILE",
            "=" * 70,
            "This file turns the labels in the de-identified documents back into",
            "real names. Keep it private. Never upload it, paste it into an AI",
            "tool, or store it with the de-identified copies.",
            "",
            f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "LABEL  ->  REAL NAME",
            "-" * 70,
        ]
        width = max(len(label) for label, _ in entries)
        for label, real_name in entries:
            lines.append(f"{label.ljust(width)}  ->  {real_name}")

        notes = pmap.ambiguity_notes()
        if notes:
            lines.extend([
                "",
                "NAMES SHARED BY MORE THAN ONE PERSON",
                "-" * 70,
                "Where a name on its own could mean more than one person, this is",
                "how it was labelled. Worth checking if the AI's reading looks odd.",
                "",
            ])
            lines.extend(f"- {note}" for note in notes)

        lines.append("")
        lines.append("END OF KEY")

        key_path = folder_path / KEY_FILE_NAME
        key_path.write_text("\n".join(lines), encoding='utf-8')
        return key_path
