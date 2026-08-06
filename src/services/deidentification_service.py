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

import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePath
from typing import Dict, List, Optional, Set, Tuple

import fitz  # PyMuPDF

from src.core.logger import RedactionLogger, LogEntry
from src.core.pseudonym_map import (
    ASSIGNABLE_ROLES,
    PseudonymMap,
    ROLE_LABELS,
    is_person_category,
)
from src.core.role_suggester import suggest_role
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

# Cell separator used while assembling a native page. It is WHITESPACE to the
# regex engine, so replacement and verification bridge it exactly like a
# newline — then it is swapped for " | " only AFTER substitution and
# verification. Decorating first would let a multi-word PII value straddle a
# " | " join, where it can neither be replaced nor caught by verification: a
# silent false pass, the one outcome the verify/quarantine mechanism exists to
# prevent.
_CELL_SEP = "\u2028"

# Blocks whose vertical midpoints are within this many points are one row.
_ROW_TOLERANCE_PT = 4.0
# A vertical gap this many times the typical row height is a paragraph break.
_PARAGRAPH_GAP_FACTOR = 1.4


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
    # The user's answers from the "Who's who?" screen, keyed by discovered full
    # name. Absent keys keep their default role, which is always safe.
    person_roles: Dict[str, str] = field(default_factory=dict)
    person_custom_labels: Dict[str, str] = field(default_factory=dict)
    # Names the user marked "not a person" (NER junk). Not registered as people;
    # their text is still replaced via its category fallback.
    ignored_people: List[str] = field(default_factory=list)


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
    # True when the user chose to write output into the folder that holds the
    # originals. The key file lands there too — but so do the unredacted source
    # documents, so the folder was never shareable wholesale. The UI must warn
    # instead of reassuring; see _output_shares_source_folder().
    output_folder_holds_originals: bool = False
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

    @staticmethod
    def build_map(request: 'DeidentifyRequest'):
        """
        Build the PseudonymMap for a run and apply the user's role answers.

        Shared by execute() and the classification endpoints so all three see
        the identical set of people and labels. Registers ONLY selected matches:
        a person whose sole occurrence the user deselected is never replaced, so
        offering them for classification would be misleading.
        """
        pmap = PseudonymMap(
            student_name=request.student_name,
            parent_names=request.parent_names,
            family_names=request.family_names,
            organisation_names=request.organisation_names,
        )

        ignored = {' '.join(n.lower().split()) for n in (request.ignored_people or [])}

        selected_by_doc = {
            doc: DeidentificationService._selected_matches(
                doc, request.detected_pii, request.user_selections)
            for doc in request.documents
        }
        for doc in request.documents:
            for match in selected_by_doc[doc]:
                if not is_person_category(getattr(match, 'category', '')):
                    continue
                if ' '.join((match.text or '').lower().split()) in ignored:
                    continue
                pmap.register_person(match.text)

        for name, role in (request.person_roles or {}).items():
            pmap.assign_role(name, role, (request.person_custom_labels or {}).get(name))

        return pmap, selected_by_doc

    @staticmethod
    def describe_people(request: 'DeidentifyRequest') -> List[dict]:
        """
        Everyone the run will label, with a proposed role and the evidence for
        it, for the "Who's who?" screen.

        Carries real names by construction — response only, never written to
        disk or into the audit log.
        """
        pmap, selected_by_doc = DeidentificationService.build_map(request)

        contexts: Dict[str, List[str]] = {}
        counts: Dict[str, int] = {}
        for doc in request.documents:
            for match in selected_by_doc[doc]:
                if not is_person_category(getattr(match, 'category', '')):
                    continue
                owner_name = pmap.resolve_owner_name(match.text)
                if not owner_name:
                    continue
                counts[owner_name] = counts.get(owner_name, 0) + 1
                if getattr(match, 'context', ''):
                    contexts.setdefault(owner_name, []).append(match.context)

        people = []
        for info in pmap.people():
            if info.source == 'entered':
                # Which box the user typed this name into IS the answer; don't
                # second-guess it with a keyword scan.
                suggested, confidence, evidence, snippet = info.role, 'entered', '', ''
            else:
                s = suggest_role(info.full_name, contexts.get(info.full_name, []))
                suggested, confidence = s.role_key, s.confidence
                evidence, snippet = s.evidence, s.snippet
            people.append({
                'full_name': info.full_name,
                'label': info.label,
                'role': info.role,
                'custom_label': info.custom_label,
                'suggested_role': suggested,
                'confidence': confidence,
                'evidence': evidence,
                'snippet': snippet,
                'occurrences': counts.get(info.full_name, 0),
                'source': info.source,
            })
        return people

    @staticmethod
    def preview_labels(request: 'DeidentifyRequest') -> Dict[str, str]:
        """
        Label each person would get under the proposed assignment.

        Exists so the screen's live preview is computed by this one Python
        implementation rather than a TypeScript reimplementation of the
        stem-and-numbering rules, which would drift (see CLAUDE.md rule 45).
        Returns EVERY person because reassigning one can renumber the others.
        """
        pmap, _ = DeidentificationService.build_map(request)
        return {info.full_name: info.label for info in pmap.people()}

    def execute(self, request: DeidentifyRequest, should_cancel=None) -> DeidentifyResults:
        output_folder = self._prepare_output_folder(
            request.folder_path, request.folder_action, request.custom_output_path
        )

        # The log header would otherwise carry the real student name.
        logger = RedactionLogger(request.folder_path, LOG_STUDENT_PLACEHOLDER)

        # Registering every person up front keeps labels consistent across all
        # documents in the run — the same teacher must not be [Teacher 2] in one
        # file and [Teacher 5] in the next.
        pmap, selected_by_doc = self.build_map(request)


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
        results.output_folder_holds_originals = self._same_folder(
            output_folder, request.folder_path
        )
        results.key_file_path = self._write_key_file(
            request.folder_path, pmap, results.document_results,
            shares_output_folder=results.output_folder_holds_originals,
        )

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
    def _same_folder(a: Path, b: Path) -> bool:
        """
        Whether two paths are the same directory.

        Uses os.path.samefile so it catches the case-insensitive-filesystem and
        symlink variants a string compare misses — the same reasoning as
        is_same_file() in redactor.py.
        """
        try:
            return a.exists() and b.exists() and os.path.samefile(str(a), str(b))
        except OSError:
            return False

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
    def _format_native_page(page, drop_header_footer: bool) -> str:
        """
        Rebuild a native page's text from LINE geometry ("dict" mode — blocks
        merge too aggressively to tell a table row from a paragraph).

        - Lines sharing a row (y-midpoints within tolerance) are table cells:
          sorted by x, joined with _CELL_SEP (decorated to " | " later).
        - A single wide line followed closely by another at the same left edge
          is wrapped prose: joined into a paragraph. Width matters — stacked
          narrow lines (headings, single-column cells) stay separate.
        - A vertical gap much larger than the typical line height becomes a
          blank line.
        - Header/footer lines are dropped by GEOMETRY when requested — strictly
          more precise than matching strings, which deleted body lines that
          merely repeated a letterhead line.

        Known limits (cosmetic only): genuinely multi-column layouts and
        rotated stamps can get pipe-joined onto shared rows.
        """
        height = page.rect.height
        header_y = height * HEADER_ZONE_FRACTION
        footer_y = height * (1 - FOOTER_ZONE_FRACTION)

        items = []
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                x0, y0, x1, y1 = line["bbox"]
                if drop_header_footer and (y1 <= header_y or y0 >= footer_y):
                    continue
                text = " ".join(
                    "".join(span.get("text", "") for span in line.get("spans", [])).split()
                )
                if text:
                    items.append((y0, y1, x0, x1, text))
        if not items:
            return ""
        items.sort(key=lambda t: (t[0], t[2]))

        rows = []
        for y0, y1, x0, x1, text in items:
            mid = (y0 + y1) / 2
            if rows and abs(mid - rows[-1]["mid"]) <= _ROW_TOLERANCE_PT:
                rows[-1]["cells"].append((x0, x1, text))
                rows[-1]["y1"] = max(rows[-1]["y1"], y1)
            else:
                rows.append({"mid": mid, "y0": y0, "y1": y1,
                             "cells": [(x0, x1, text)]})

        heights = sorted(r["y1"] - r["y0"] for r in rows)
        typical = heights[len(heights) // 2] or 12.0
        max_width = max(x1 - x0 for _, _, x0, x1, _ in [
            (0, 0, c[0], c[1], c[2]) for r in rows for c in r["cells"]
        ]) or 1.0

        # units: list of [text, is_multicell, y0, y1, x0, width_of_last_line]
        units = []
        for row in rows:
            cells = sorted(row["cells"])
            multi = len(cells) > 1
            text = _CELL_SEP.join(c[2] for c in cells)
            x0, x1 = cells[0][0], cells[-1][1]
            gap = row["y0"] - units[-1][3] if units else None

            # Wrapped prose: previous unit is a single WIDE line, this row is a
            # single line starting at the same left edge, tightly below it.
            if (units and not multi and not units[-1][1]
                    and gap is not None and gap < 0.5 * typical
                    and abs(x0 - units[-1][4]) < 3
                    and units[-1][5] > 0.5 * max_width):
                units[-1][0] += " " + text
                units[-1][3] = row["y1"]
                units[-1][5] = x1 - x0
                continue

            if units and gap is not None and gap > _PARAGRAPH_GAP_FACTOR * typical:
                units.append(["", False, row["y0"], row["y0"], x0, 0])

            units.append([text, multi, row["y0"], row["y1"], x0, x1 - x0])

        return "\n".join(u[0] for u in units)

    def _formatted_pages(self, doc_path: Path, pages: Dict, ocr_pages: Set[int],
                         drop_header_footer: bool) -> Dict[int, str]:
        """
        Text per page for the OUTPUT file.

        Native pages come from block geometry, with AcroForm widget values
        appended — they live outside the content stream, so a geometry rebuild
        alone would silently drop content (and PII) the extractor was
        specifically taught to catch. OCR pages keep their cached text: no
        geometry. ANY failure falls back to the cached raw text for that page —
        formatting must never fail a run.
        """
        from src.core.text_extractor import TextExtractor
        extractor = TextExtractor()

        out: Dict[int, str] = {}
        pdf = None
        try:
            pdf = fitz.open(str(doc_path))
        except Exception:
            pdf = None
        try:
            for page_num in sorted(pages):
                cached = pages[page_num].get('text', '') or ''
                if page_num in ocr_pages or pdf is None or page_num > len(pdf):
                    out[page_num] = cached
                    continue
                try:
                    page = pdf[page_num - 1]
                    text = self._format_native_page(page, drop_header_footer)
                    widget_text = extractor._extract_widget_values(page)
                    if widget_text:
                        text = (text.rstrip() + '\n' + widget_text) if text else widget_text
                    out[page_num] = text if text else cached
                except Exception:
                    out[page_num] = cached
        finally:
            if pdf is not None:
                pdf.close()
        return out

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
        # The result's document_name is the source filename because the UI shows
        # it to the user locally. Everything written to DISK uses safe_name —
        # documents are routinely called "Billy Bob Support Report.pdf", so the
        # source filename in a shareable artifact leaks the very name being
        # removed.
        safe_name = f"{strip_pii_from_filename(doc.stem, name_variations or [])}.pdf"

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
            logger.add_flagged_file(safe_name, result.error_message)
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
            logger.add_flagged_file(safe_name, message)
            result.error_message = message
            return result

        # Layout-aware text for the output (cells joined with _CELL_SEP for
        # now). Replace page by page so OCR-sourced output can be verified
        # separately. Every selected match is applied to every page: a name
        # detected on page one must also go from page five.
        formatted = self._formatted_pages(doc, pages, ocr_pages, drop_header_footer)
        page_outputs: Dict[int, str] = {}
        total_replacements = 0
        for page_num in sorted(pages):
            cleaned, count = deidentify_text(formatted[page_num], selected_matches, pmap)
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

        # Verification runs BEFORE decoration: full_output still uses the
        # whitespace cell separator, so the verify patterns bridge cell joins
        # exactly as the replace pass did. Decorating first would blind both
        # passes to a PII value straddling a table-cell boundary.
        leftovers = verify_deidentified(full_output, selected_texts, labels)
        for page_num in sorted(ocr_pages & set(page_outputs)):
            for item in fuzzy_leftovers(page_outputs[page_num], selected_texts, labels):
                if item not in leftovers:
                    leftovers.append(item)

        # Only now do cell separators become visible table dividers.
        full_output = full_output.replace(_CELL_SEP, ' | ')

        for match in selected_matches:
            logger.add_entry(LogEntry(
                # The stripped output name, never the source filename: documents
                # are routinely named after the student.
                document_name=output_filename,
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
            self._write_text(quarantine, full_output, total_replacements)
            result.quarantine_path = quarantine
            result.verification_failures = [
                f"Possible remaining reference to \"{item}\"" for item in leftovers
            ]
            logger.add_flagged_file(
                quarantine.name,
                f"Verification found {len(leftovers)} possible remaining reference(s); "
                f"saved as {quarantine.name} for manual review",
            )
            return result

        try:
            self._write_text(output_path, full_output, total_replacements)
        except Exception as e:
            result.error_message = f"Could not write output file: {e}"
            logger.add_flagged_file(safe_name, result.error_message)
            return result

        result.output_path = output_path
        result.success = True
        return result

    @staticmethod
    def _write_text(path: Path, body: str, replacements: int = 0) -> None:
        # Deliberately no source filename: documents are routinely named after
        # the student ("Billy Bob Support Report.pdf"), so naming the original
        # here would print the very name the rest of the file removed. The
        # original-to-output mapping lives in the key file instead.
        if replacements:
            header = (
                "De-identified copy — names and personal details have been "
                "replaced with labels such as [Student] and [Teacher 1].\n"
            )
        else:
            # Claiming a de-identified copy when nothing was replaced would be a
            # lie the filename already half-tells. Say so plainly instead.
            header = (
                "WARNING — NOTHING WAS REPLACED IN THIS FILE.\n"
                "No personal information was detected, so this is the document's "
                "text exactly as it was.\n"
                "Read it before sharing it or pasting it anywhere.\n"
            )
        header += f"{'=' * 70}\n\n"
        path.write_text(header + body, encoding='utf-8')

    # ── Key file ─────────────────────────────────────────────────────────

    @staticmethod
    def _write_key_file(folder_path: Path, pmap: PseudonymMap,
                        document_results: List[DeidentifyDocumentResult] = None,
                        shares_output_folder: bool = False,
                        ) -> Optional[Path]:
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
        ]

        if shares_output_folder:
            lines.extend([
                "!! You chose to save the de-identified files into this same",
                "!! folder, which also holds your ORIGINAL documents and this",
                "!! key. Do not share the folder itself.",
                "!! Send the individual .txt files instead.",
                "",
            ])

        lines.extend([
            f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "LABEL  ->  REAL NAME",
            "-" * 70,
        ])
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

        # The output filenames have the student's details stripped, so this is
        # the only place the two can be matched up — and it belongs here, in the
        # file that is already private, rather than in the shareable audit log.
        rows = [
            (r.document_name,
             (r.output_path or r.quarantine_path).name if (r.output_path or r.quarantine_path)
             else "(not produced)")
            for r in (document_results or [])
        ]
        if rows:
            lines.extend([
                "",
                "WHICH FILE CAME FROM WHICH",
                "-" * 70,
            ])
            width = max(len(original) for original, _ in rows)
            for original, produced in rows:
                lines.append(f"{original.ljust(width)}  ->  {produced}")

        lines.append("")
        lines.append("END OF KEY")

        key_path = folder_path / KEY_FILE_NAME
        key_path.write_text("\n".join(lines), encoding='utf-8')
        return key_path
