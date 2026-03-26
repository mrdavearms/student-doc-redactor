"""
Text Extractor
Extracts text from PDFs using native text layer and OCR fallback.
"""

import os
import unicodedata

import fitz  # PyMuPDF
from pathlib import Path
from typing import Dict, List, Tuple
import pytesseract
from PIL import Image
import io

def _normalise_text(text: str) -> str:
    """NFKC normalise and replace smart quotes with ASCII equivalents."""
    text = unicodedata.normalize('NFKC', text)
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    text = text.replace('\u201C', '"').replace('\u201D', '"')
    return text


class TextExtractor:
    """Extracts text from PDF documents with OCR support"""

    def __init__(self):
        from binary_resolver import resolve_tesseract, resolve_tessdata
        tesseract_path = resolve_tesseract()
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
        tessdata_path = resolve_tessdata()
        if tessdata_path:
            os.environ.setdefault("TESSDATA_PREFIX", tessdata_path)
        self.tesseract_available = self._check_tesseract()

    def _check_tesseract(self) -> bool:
        """Check if Tesseract is installed and accessible"""
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def extract_text_from_pdf(self, pdf_path: Path) -> Dict:
        """
        Extract text from PDF with OCR fallback for image-based pages

        Args:
            pdf_path: Path to PDF file

        Returns:
            Dictionary with:
            {
                'pages': {
                    page_num: {
                        'text': str,
                        'method': 'native' or 'ocr',
                        'confidence': float (for OCR),
                        'blocks': List[Dict]  # Text blocks with coordinates
                    }
                },
                'total_pages': int,
                'ocr_pages': List[int]  # Pages that required OCR
            }
        """
        result = {
            'pages': {},
            'total_pages': 0,
            'ocr_pages': []
        }

        try:
            with fitz.open(str(pdf_path)) as doc:
                result['total_pages'] = len(doc)

                for page_num in range(len(doc)):
                    page = doc[page_num]
                    page_data = self._extract_page_text(page, page_num + 1)
                    result['pages'][page_num + 1] = page_data

                    if page_data['method'] == 'ocr':
                        result['ocr_pages'].append(page_num + 1)

        except Exception as e:
            raise Exception(f"Error extracting text from PDF: {str(e)}")

        return result

    def _extract_page_text(self, page: fitz.Page, page_num: int) -> Dict:
        """
        Extract text from a single page, using OCR if needed.
        Also extracts values from PDF form widgets (AcroForm fields),
        which are stored in a separate layer from the content stream.

        Args:
            page: PyMuPDF page object
            page_num: Page number (1-indexed)

        Returns:
            Dictionary with page text and metadata
        """
        # Try native text extraction first
        text = _normalise_text(page.get_text())
        blocks = page.get_text("dict")["blocks"]

        # Extract form widget values (AcroForm fields live outside the content stream)
        widget_text = self._extract_widget_values(page)
        if widget_text:
            text = text.rstrip() + "\n" + widget_text

        # Check if page has meaningful text
        if len(text.strip()) > 50:  # Arbitrary threshold - adjust as needed
            return {
                'text': text,
                'method': 'native',
                'confidence': 1.0,
                'blocks': self._format_blocks(blocks, page_num)
            }

        # Fallback to OCR
        if self.tesseract_available:
            ocr_text, confidence = self._ocr_page(page)
            return {
                'text': ocr_text,
                'method': 'ocr',
                'confidence': confidence,
                'blocks': self._format_ocr_blocks(ocr_text, page_num)
            }
        else:
            # No OCR available, return whatever we got
            return {
                'text': text,
                'method': 'native',
                'confidence': 0.5,  # Low confidence
                'blocks': self._format_blocks(blocks, page_num)
            }

    def _extract_widget_values(self, page: fitz.Page) -> str:
        """
        Extract text values from PDF form widgets (AcroForm fields).

        Form field values live in a separate layer from the page content stream
        and are invisible to page.get_text(). This method reads them via the
        widget API so the PII detector can find names in filled form fields.

        Returns:
            Newline-joined string of non-empty widget values, or empty string.
        """
        values = []
        try:
            for widget in page.widgets():
                val = widget.field_value
                if val and isinstance(val, str) and val.strip():
                    values.append(val.strip())
        except Exception:
            pass  # Page has no widgets or widget API unavailable
        return "\n".join(values)

    def _ocr_page(self, page: fitz.Page) -> Tuple[str, float]:
        """
        Perform OCR on a page

        Args:
            page: PyMuPDF page object

        Returns:
            Tuple of (text, confidence)
        """
        try:
            # Convert page to image
            pix = page.get_pixmap(dpi=300)  # High DPI for better OCR
            img = Image.open(io.BytesIO(pix.tobytes()))

            # Run OCR
            ocr_data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

            # Extract text with line structure preserved
            confidences = []
            current_line_key = None
            lines_out = []
            current_words = []
            for i, word in enumerate(ocr_data['text']):
                if int(ocr_data['conf'][i]) < 0 or not str(word).strip():
                    continue
                conf = int(ocr_data['conf'][i])
                if conf > 0:
                    confidences.append(conf)
                line_key = (ocr_data['block_num'][i], ocr_data['line_num'][i])
                if line_key != current_line_key:
                    if current_words:
                        lines_out.append(' '.join(current_words))
                    current_words = [str(word)]
                    current_line_key = line_key
                else:
                    current_words.append(str(word))
            if current_words:
                lines_out.append(' '.join(current_words))
            text = _normalise_text('\n'.join(lines_out))
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0
            confidence = avg_confidence / 100.0  # Convert to 0-1 scale

            return text, confidence

        except Exception as e:
            print(f"OCR error: {str(e)}")
            return "", 0.0

    def _format_blocks(self, blocks: List, page_num: int) -> List[Dict]:
        """Format text blocks with coordinates"""
        formatted = []
        for block in blocks:
            if block.get('type') == 0:  # Text block
                formatted.append({
                    'page': page_num,
                    'bbox': block['bbox'],  # (x0, y0, x1, y1)
                    'text': block.get('text', ''),
                    'lines': block.get('lines', [])
                })
        return formatted

    def _format_ocr_blocks(self, text: str, page_num: int) -> List[Dict]:
        """Format OCR text as simple blocks (no precise coordinates available)"""
        # For OCR, we don't have precise coordinates, so create a single block
        return [{
            'page': page_num,
            'bbox': None,
            'text': text,
            'lines': text.split('\n')
        }]

    def get_text_with_coordinates(self, pdf_path: Path, page_num: int) -> List[Tuple[str, Tuple[float, float, float, float]]]:
        """
        Extract text with bounding box coordinates for a specific page

        Args:
            pdf_path: Path to PDF
            page_num: Page number (1-indexed)

        Returns:
            List of tuples: (text, (x0, y0, x1, y1))
        """
        results = []

        try:
            doc = fitz.open(str(pdf_path))
            page = doc[page_num - 1]

            # Get text with coordinates
            blocks = page.get_text("dict")["blocks"]

            for block in blocks:
                if block.get('type') == 0:  # Text block
                    for line in block.get('lines', []):
                        for span in line.get('spans', []):
                            text = span.get('text', '').strip()
                            bbox = span.get('bbox')
                            if text and bbox:
                                results.append((text, bbox))

            doc.close()

        except Exception as e:
            print(f"Error extracting coordinates: {str(e)}")

        return results
