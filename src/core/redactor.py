"""
Redaction Engine
Permanently redacts PII from PDFs by removing underlying text and adding black boxes.
Supports both text-layer redaction and OCR-based image redaction for scanned pages.
"""

import io
import os
import re
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Dict, Tuple
from dataclasses import dataclass
from PIL import Image, ImageDraw
import pytesseract


# Zone redaction fractions — fraction of page height to blank
HEADER_ZONE_FRACTION = 0.12   # top 12%
FOOTER_ZONE_FRACTION = 0.08   # bottom 8%


def strip_pii_from_filename(stem: str, name_variations: List[str]) -> str:
    """
    Remove PII name tokens from a filename stem, preserving document-type words.

    Args:
        stem: Filename without extension (e.g. "Joe Bloggs DIP Vineland Report 2025")
        name_variations: List of name strings to strip (student, parents, family).
                         Entries shorter than 3 chars are ignored.

    Returns:
        Cleaned stem, or "document" if the result is too short to be meaningful.
    """
    if not name_variations:
        return stem

    # Normalize underscores → spaces so word boundaries work on "Bloggs_Joe_..." format
    result = stem.replace('_', ' ')

    # Sort longest-first: strip "Joe Bloggs" before "Joe" to avoid orphaned fragments
    sorted_variations = sorted(name_variations, key=len, reverse=True)

    for variation in sorted_variations:
        if len(variation) < 3:
            continue
        pattern = re.compile(r'\b' + re.escape(variation) + r'\b', re.IGNORECASE)
        result = pattern.sub('', result)

    # Remove possessive remnants: "Joe's" → "'s" → ""
    result = re.sub(r"'s\b", '', result)

    # Collapse runs of spaces
    result = re.sub(r' {2,}', ' ', result)

    # Remove empty brackets left by name removal: "( )", "[]", "(  )"
    result = re.sub(r'\(\s*\)', '', result)
    result = re.sub(r'\[\s*\]', '', result)

    # Collapse double separators: "Plan -  - Report" or "Plan - - Report" → "Plan - Report"
    result = re.sub(r'(\s*-\s*){2,}', ' - ', result)

    # Remove orphaned separator before an opening bracket: "Plan - (T1 2024)" → "Plan (T1 2024)"
    result = re.sub(r'\s*-\s*(?=[\(\[])', ' ', result)

    # Strip leading/trailing separators and whitespace
    result = result.strip(' -_,.')

    # Final space normalise
    result = re.sub(r' {2,}', ' ', result).strip()

    # Fallback: if result is empty or too short to be a real name, use generic label
    if len(result) < 3:
        return 'document'

    return result


@dataclass
class RedactionItem:
    """Represents an item to be redacted"""
    page_num: int
    text: str
    bbox: Tuple[float, float, float, float] = None  # (x0, y0, x1, y1)

class PDFRedactor:
    """Handles permanent redaction of PDF documents"""

    def __init__(self):
        pass

    def redact_pdf(self, input_pdf: Path, output_pdf: Path, redaction_items: List[RedactionItem], redact_header_footer: bool = False) -> Tuple[bool, str]:
        """
        Create a redacted copy of a PDF

        Args:
            input_pdf: Path to source PDF
            output_pdf: Path to save redacted PDF
            redaction_items: List of items to redact

        Returns:
            Tuple of (success, message)
        """
        try:
            doc = fitz.open(str(input_pdf))

            # ── Stage 0: Zone redaction (header/footer blanking) ──
            # Runs on EVERY page, not just pages with detected PII.
            if redact_header_footer:
                for page in doc:
                    self._redact_zones(page)

            # Group redactions by page for efficiency
            redactions_by_page = {}
            for item in redaction_items:
                if item.page_num not in redactions_by_page:
                    redactions_by_page[item.page_num] = []
                redactions_by_page[item.page_num].append(item)

            # Apply redactions page by page
            ocr_redacted_count = 0
            image_redacted_count = 0
            for page_num, items in redactions_by_page.items():
                page = doc[page_num - 1]  # Convert to 0-indexed

                if self._is_image_only_page(page):
                    # Image-only page: render → OCR → draw black rects on image → replace page
                    ocr_hits = self._redact_ocr_page(page, items)
                    ocr_redacted_count += ocr_hits
                    # No apply_redactions needed — _redact_ocr_page replaces the page image directly
                else:
                    # Text-layer page: standard redaction
                    for item in items:
                        if item.bbox:
                            # We have precise coordinates - use them
                            self._redact_bbox(page, item.bbox)
                        else:
                            # Search for text and redact all instances
                            self._redact_text_search(page, item.text)

                    # Apply all redactions on this page
                    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

                # Stage 2: Scan every embedded image on this page for PII.
                # Runs on ALL pages — text-layer, image-only, and hybrid.
                # This catches PII in embedded screenshots, email printouts,
                # logos with names, etc. that text-layer redaction cannot reach.
                image_redacted_count += self._redact_embedded_images(page, items)

                # Stage 3: Delete form widgets whose values contain redacted PII.
                # apply_redactions() only removes content-stream text; AcroForm
                # widget field values live in annotation dictionaries and survive
                # redaction.  Deleting the widget is the only reliable way to
                # remove the data.
                redacted_texts = [item.text.lower() for item in items]
                self._delete_pii_widgets(page, redacted_texts)

            # Strip metadata before saving
            self._strip_metadata(doc)

            # Save redacted document (clean=True removes incremental save data)
            doc.save(str(output_pdf), garbage=4, deflate=True, clean=True)
            doc.close()

            return True, f"Successfully redacted {len(redaction_items)} items"

        except Exception as e:
            return False, f"Error during redaction: {str(e)}"

    def _redact_bbox(self, page: fitz.Page, bbox: Tuple[float, float, float, float]):
        """
        Redact a specific bounding box

        Args:
            page: PyMuPDF page object
            bbox: Bounding box coordinates (x0, y0, x1, y1)
        """
        # Create redaction annotation
        rect = fitz.Rect(bbox)
        # Add a bit of padding to ensure complete coverage
        rect = rect + (-1, -1, 1, 1)
        page.add_redact_annot(rect, fill=(0, 0, 0))  # Black fill

    def _redact_text_search(self, page: fitz.Page, text: str):
        """
        Search for text and redact all whole-word instances.

        For texts ≤ 6 characters, each match rect is verified against the page
        word list to avoid partial-word erasure (e.g. 'Ann' inside 'Annual').
        Texts shorter than 3 characters are skipped entirely.
        """
        if len(text) < 3:
            return

        text_instances = page.search_for(text, flags=fitz.TEXT_PRESERVE_WHITESPACE)
        if not text_instances:
            return

        if len(text) <= 6:
            # Short text: verify each rect aligns with a complete word to avoid partial erasure
            word_rects = [(fitz.Rect(w[:4]), w[4]) for w in page.get_text("words")]
            for rect in text_instances:
                if self._is_whole_word_match(rect, text, word_rects):
                    page.add_redact_annot(rect + (-1, -1, 1, 1), fill=(0, 0, 0))
        else:
            for rect in text_instances:
                page.add_redact_annot(rect + (-1, -1, 1, 1), fill=(0, 0, 0))

    def _is_whole_word_match(
        self,
        match_rect: fitz.Rect,
        text: str,
        word_rects: list,
    ) -> bool:
        """
        Return True if match_rect substantially overlaps a word whose text
        equals `text` (case-insensitive), optionally followed by a possessive
        suffix ('s / 's) or non-alphanumeric characters (punctuation like ",").
        """
        needle = text.strip().lower()
        for word_rect, word_text in word_rects:
            word_clean = word_text.strip().lower()
            if not word_clean.startswith(needle):
                continue
            remainder = word_clean[len(needle):]
            # Exact match, possessive suffix, or purely non-alphanumeric tail
            if (
                not remainder
                or remainder in ("'s", "\u2019s")
                or not any(c.isalnum() for c in remainder)
            ):
                intersection = match_rect & word_rect
                if intersection.is_valid and intersection.get_area() >= 0.7 * match_rect.get_area():
                    return True
        return False

    def _is_image_only_page(self, page: fitz.Page) -> bool:
        """
        Detect whether a page is image-only (scanned/screenshot with no usable text layer).

        Returns True if the page has no meaningful text but contains at least one image.
        """
        words = page.get_text("words")
        images = page.get_images(full=True)
        return len(words) == 0 and len(images) > 0

    def _redact_zones(self, page: fitz.Page):
        """
        Blank header and footer zones on a single page.

        For text-layer pages: adds redaction annotations covering the zone
        rectangles and applies them (text removal + black fill).

        For image-only pages: renders to PIL, draws black rectangles over
        the zone pixel regions, and replaces the page content.
        """
        rect = page.rect
        header_y = rect.height * HEADER_ZONE_FRACTION
        footer_y = rect.height * (1 - FOOTER_ZONE_FRACTION)

        if self._is_image_only_page(page):
            # PIL path — render, paint black rects, replace page image
            dpi = 300
            scale = dpi / 72
            pix = page.get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            draw = ImageDraw.Draw(img)

            # Header zone (top of image)
            draw.rectangle(
                [0, 0, img.width, int(header_y * scale)],
                fill="black",
            )
            # Footer zone (bottom of image)
            draw.rectangle(
                [0, int(footer_y * scale), img.width, img.height],
                fill="black",
            )

            img_bytes = io.BytesIO()
            img.save(img_bytes, format="PNG")
            img_bytes.seek(0)

            page.clean_contents()
            doc = page.parent
            for xref in page.get_contents():
                doc.update_stream(xref, b"")
            page.insert_image(page.rect, stream=img_bytes.read(), overlay=True)
        else:
            # Text-layer path — PyMuPDF redaction annotations
            header_rect = fitz.Rect(rect.x0, rect.y0, rect.x1, header_y)
            footer_rect = fitz.Rect(rect.x0, footer_y, rect.x1, rect.y1)

            page.add_redact_annot(header_rect, fill=(0, 0, 0))
            page.add_redact_annot(footer_rect, fill=(0, 0, 0))
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

    def _check_tesseract(self) -> bool:
        """Check if Tesseract is installed and accessible."""
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def _match_and_redact_ocr_words(
        self,
        draw: 'ImageDraw.ImageDraw',
        ocr_words: list,
        items: List['RedactionItem'],
        padding: int = 4,
    ) -> int:
        """
        Draw black rectangles over OCR words that match any PII item.

        Shared helper used by both _redact_ocr_page() (full-page OCR) and
        _redact_embedded_images() (per-image OCR).

        Args:
            draw: PIL ImageDraw instance already bound to the target image.
            ocr_words: List of (word_text, (x0, y0, x1, y1)) tuples in pixel space.
            items: RedactionItems to locate and cover.
            padding: Extra pixels of coverage around each matched bbox.

        Returns:
            Number of PII word-groups successfully redacted.
        """
        redacted_count = 0

        for item in items:
            pii_text = item.text.strip()
            if len(pii_text) < 3:
                continue

            pii_lower = pii_text.lower()
            pii_words = pii_lower.split()

            if len(pii_words) == 1:
                # Single-word PII: match individual OCR words
                for ocr_word, pixel_bbox in ocr_words:
                    ocr_lower = ocr_word.lower()
                    # Preserve curly apostrophes in cleaned form
                    ocr_clean = re.sub(r"[^\w'\u2019]", '', ocr_lower)
                    if (
                        ocr_clean == pii_lower
                        or ocr_clean == pii_lower + "'s"
                        or ocr_clean == pii_lower + "\u2019s"
                        or ocr_clean.rstrip(".,;:!?") == pii_lower
                        # Exact match for PII with special chars (emails, URLs)
                        or (not pii_lower.isalpha() and pii_lower in ocr_lower)
                    ):
                        x0, y0, x1, y1 = pixel_bbox
                        draw.rectangle(
                            [x0 - padding, y0 - padding, x1 + padding, y1 + padding],
                            fill="black",
                        )
                        redacted_count += 1
            else:
                # Multi-word PII (e.g. "Joe Bloggs"): find consecutive OCR words
                for start_idx in range(len(ocr_words) - len(pii_words) + 1):
                    match = True
                    for wi, pii_w in enumerate(pii_words):
                        ocr_w = ocr_words[start_idx + wi][0]
                        ocr_clean = re.sub(r"[^\w']", '', ocr_w.lower())
                        if ocr_clean != pii_w and ocr_clean.rstrip(".,;:!?") != pii_w:
                            match = False
                            break
                    if match:
                        first_bbox = ocr_words[start_idx][1]
                        last_bbox = ocr_words[start_idx + len(pii_words) - 1][1]
                        x0 = min(first_bbox[0], last_bbox[0])
                        y0 = min(first_bbox[1], last_bbox[1])
                        x1 = max(first_bbox[2], last_bbox[2])
                        y1 = max(first_bbox[3], last_bbox[3])
                        draw.rectangle(
                            [x0 - padding, y0 - padding, x1 + padding, y1 + padding],
                            fill="black",
                        )
                        redacted_count += 1

        return redacted_count

    def _redact_embedded_images(self, page: fitz.Page, items: list) -> int:
        """
        Scan each embedded image on a page with OCR and black out any PII found.

        Used for hybrid pages (text layer + embedded images) where text-layer
        redaction misses PII baked into the image pixels.

        Returns the total number of words redacted across all images on the page.
        """
        images = page.get_images(full=True)
        if not images:
            return 0
        if not self._check_tesseract():
            return 0

        try:
            from binary_resolver import resolve_tesseract, resolve_tessdata
            tesseract_path = resolve_tesseract()
            if tesseract_path:
                pytesseract.pytesseract.tesseract_cmd = tesseract_path
            tessdata_path = resolve_tessdata()
            if tessdata_path:
                os.environ.setdefault("TESSDATA_PREFIX", tessdata_path)
        except ImportError:
            pass

        doc = page.parent
        total_redacted = 0

        for img_info in images:
            xref = img_info[0]
            try:
                img_dict = doc.extract_image(xref)
            except Exception:
                continue
            if not img_dict or not img_dict.get('image'):
                continue

            img_bytes = img_dict['image']
            try:
                pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            except Exception:
                continue

            ocr_data = pytesseract.image_to_data(pil_img, output_type=pytesseract.Output.DICT)
            ocr_words = []
            for i in range(len(ocr_data['text'])):
                word = ocr_data['text'][i].strip()
                if not word:
                    continue
                x = ocr_data['left'][i]
                y = ocr_data['top'][i]
                w = ocr_data['width'][i]
                h = ocr_data['height'][i]
                ocr_words.append((word, (x, y, x + w, y + h)))

            if not ocr_words:
                continue

            draw = ImageDraw.Draw(pil_img)
            redacted_count = self._match_and_redact_ocr_words(draw, ocr_words, items)
            if redacted_count == 0:
                continue

            out_buf = io.BytesIO()
            pil_img.save(out_buf, format="PNG")
            out_buf.seek(0)
            try:
                page.replace_image(xref, stream=out_buf.read())
            except Exception:
                continue
            total_redacted += redacted_count

        return total_redacted

    def _redact_ocr_page(self, page: fitz.Page, items: List['RedactionItem']) -> int:
        """
        Redact PII on an image-only page using OCR to locate words.

        Renders the page at 300 DPI, OCRs to get word bounding boxes,
        draws opaque black rectangles over matching regions on the PIL
        image, then replaces the page content with the modified image.

        Cannot use add_redact_annot + apply_redactions here because
        PDF_REDACT_IMAGE_REMOVE would destroy the entire full-page scan
        image (the whole page IS one image on scanned PDFs).

        Args:
            page: PyMuPDF page object (image-only — no text layer).
            items: RedactionItems to locate and cover.

        Returns:
            Number of PII word-groups successfully redacted via OCR.
        """
        if not self._check_tesseract():
            return 0

        # Resolve Tesseract paths using the same binary_resolver as TextExtractor
        try:
            from binary_resolver import resolve_tesseract, resolve_tessdata
            tesseract_path = resolve_tesseract()
            if tesseract_path:
                pytesseract.pytesseract.tesseract_cmd = tesseract_path
            tessdata_path = resolve_tessdata()
            if tessdata_path:
                os.environ.setdefault("TESSDATA_PREFIX", tessdata_path)
        except ImportError:
            pass  # binary_resolver not available — use system defaults

        # Render page at 300 DPI for high-quality OCR
        dpi = 300
        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")

        # OCR with word-level bounding boxes
        ocr_data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

        # Build list of (word_text, pixel_bbox) from OCR output
        ocr_words = []
        for i in range(len(ocr_data['text'])):
            word = ocr_data['text'][i].strip()
            if not word:
                continue
            x = ocr_data['left'][i]
            y = ocr_data['top'][i]
            w = ocr_data['width'][i]
            h = ocr_data['height'][i]
            ocr_words.append((word, (x, y, x + w, y + h)))

        if not ocr_words:
            return 0

        # Draw black rectangles over matching PII words via the shared helper
        draw = ImageDraw.Draw(img)
        redacted_count = self._match_and_redact_ocr_words(draw, ocr_words, items)

        if redacted_count == 0:
            return 0

        # Replace the page content with the redacted image.
        # Convert PIL image back to PNG bytes.
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_bytes.seek(0)

        # Clear the page and insert the modified image at the same dimensions.
        page_rect = page.rect
        page.clean_contents()
        doc = page.parent
        # Clear the page's content stream(s)
        for content_xref in page.get_contents():
            doc.update_stream(content_xref, b"")
        # Insert the redacted image to fill the page
        page.insert_image(page_rect, stream=img_bytes.read(), overlay=True)

        return redacted_count

    def _delete_pii_widgets(self, page: fitz.Page, redacted_texts: list):
        """
        Delete form widgets whose field values contain any of the redacted texts.

        PDF form fields (AcroForm widgets) store values in annotation
        dictionaries, which apply_redactions() does not touch. The only
        reliable way to remove the data is to delete the widget entirely.

        Args:
            page: PyMuPDF page object (already redacted).
            redacted_texts: Lowercased PII strings that were redacted on this page.
        """
        try:
            widgets = list(page.widgets())
        except Exception:
            return  # Page has no widgets or widget API unavailable

        # Collect field names to delete (don't modify iterator while iterating)
        names_to_delete = []
        for w in widgets:
            val = (w.field_value or "").strip().lower()
            if not val:
                continue
            for pii in redacted_texts:
                if pii in val:
                    names_to_delete.append(w.field_name)
                    break

        # Delete each widget in a fresh iterator pass to avoid invalidation
        for name in names_to_delete:
            try:
                for w in page.widgets():
                    if w.field_name == name:
                        page.delete_widget(w)
                        break
            except Exception:
                pass  # Widget already removed or page changed

    def verify_redaction(self, pdf_path: Path, original_text: str) -> Tuple[bool, str]:
        """
        Verify that text has been successfully redacted

        Args:
            pdf_path: Path to redacted PDF
            original_text: Text that should have been redacted

        Returns:
            Tuple of (is_redacted, message)
        """
        try:
            doc = fitz.open(str(pdf_path))
            all_text = ""

            for page in doc:
                all_text += page.get_text()

                # Also check form widget field values — these live outside the
                # content stream and are invisible to get_text().
                try:
                    for w in page.widgets():
                        val = w.field_value
                        if val and isinstance(val, str):
                            all_text += " " + val
                except Exception:
                    pass

            doc.close()

            # Check if the text still appears
            if original_text.lower() in all_text.lower():
                return False, f"Text still found in document: {original_text}"
            else:
                return True, "Text successfully redacted"

        except Exception as e:
            return False, f"Error verifying redaction: {str(e)}"

    def _strip_metadata(self, doc: fitz.Document):
        """Strip all identifying metadata from the PDF"""
        doc.set_metadata({
            "author": "",
            "title": "",
            "subject": "",
            "creator": "",
            "producer": "",
            "keywords": "",
            "creationDate": "",
            "modDate": "",
        })

        # Remove XMP metadata
        doc.del_xml_metadata()

        # Remove embedded files
        if hasattr(doc, 'embfile_count') and doc.embfile_count() > 0:
            for name in list(doc.embfile_names()):
                doc.embfile_del(name)

    def verify_redaction_ocr(self, pdf_path: Path, redacted_texts: List[str]) -> Tuple[bool, List[str]]:
        """
        Verify redaction by rendering pages as images, OCR-ing them,
        and checking that no redacted strings remain visible.

        Args:
            pdf_path: Path to the redacted PDF
            redacted_texts: List of text strings that should have been redacted

        Returns:
            Tuple of (all_clean, list_of_failure_messages)
        """
        failures = []

        try:
            doc = fitz.open(str(pdf_path))

            for page_idx in range(len(doc)):
                page = doc[page_idx]

                # Render page at 300 DPI for reliable OCR
                pix = page.get_pixmap(dpi=300)
                img = Image.open(io.BytesIO(pix.tobytes("png")))

                # OCR the rendered image
                ocr_text = pytesseract.image_to_string(img).lower()

                # Check each redacted string
                for text in redacted_texts:
                    if len(text) >= 3 and text.lower() in ocr_text:
                        failures.append(
                            f"Page {page_idx + 1}: '{text}' still visible after redaction"
                        )

            doc.close()

        except Exception as e:
            failures.append(f"OCR verification error: {str(e)}")

        return (len(failures) == 0, failures)

    def create_redacted_copy(self, input_pdf: Path, output_folder: Path, redactions: List[RedactionItem]) -> Tuple[bool, str, Path]:
        """
        Create a redacted copy with _redacted suffix

        Args:
            input_pdf: Source PDF
            output_folder: Folder to save redacted copy
            redactions: List of redaction items

        Returns:
            Tuple of (success, message, output_path)
        """
        # Create output filename
        output_filename = f"{input_pdf.stem}_redacted.pdf"
        output_path = output_folder / output_filename

        # Perform redaction
        success, message = self.redact_pdf(input_pdf, output_path, redactions)

        if success:
            return True, message, output_path
        else:
            return False, message, None

    def count_redactions_by_category(self, redactions: List[RedactionItem]) -> Dict[str, int]:
        """
        Count redactions by category

        Args:
            redactions: List of redaction items (must have 'category' attribute)

        Returns:
            Dictionary of category counts
        """
        counts = {}
        for item in redactions:
            category = getattr(item, 'category', 'Unknown')
            counts[category] = counts.get(category, 0) + 1
        return counts
