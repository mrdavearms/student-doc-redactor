"""
Redaction Engine
Permanently redacts PII from PDFs by removing underlying text and adding black boxes.
"""

import io
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Dict, Tuple
from dataclasses import dataclass
from PIL import Image
import pytesseract

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

    def redact_pdf(self, input_pdf: Path, output_pdf: Path, redaction_items: List[RedactionItem]) -> Tuple[bool, str]:
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

            # Group redactions by page for efficiency
            redactions_by_page = {}
            for item in redaction_items:
                if item.page_num not in redactions_by_page:
                    redactions_by_page[item.page_num] = []
                redactions_by_page[item.page_num].append(item)

            # Apply redactions page by page
            for page_num, items in redactions_by_page.items():
                page = doc[page_num - 1]  # Convert to 0-indexed

                for item in items:
                    if item.bbox:
                        # We have precise coordinates - use them
                        self._redact_bbox(page, item.bbox)
                    else:
                        # Search for text and redact all instances
                        self._redact_text_search(page, item.text)

                # Apply all redactions on this page
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

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
        exactly equals `text` (case-insensitive).
        """
        for word_rect, word_text in word_rects:
            if word_text.strip().lower() == text.strip().lower():
                intersection = match_rect & word_rect
                if intersection.is_valid and intersection.get_area() >= 0.7 * match_rect.get_area():
                    return True
        return False

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
