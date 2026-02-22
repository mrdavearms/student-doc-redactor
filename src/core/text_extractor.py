"""
Text Extractor
Extracts text from PDFs using native text layer and OCR fallback.
"""

import fitz  # PyMuPDF
from pathlib import Path
from typing import Dict, List, Tuple
import pytesseract
from PIL import Image
import io

class TextExtractor:
    """Extracts text from PDF documents with OCR support"""

    def __init__(self):
        # Check if Tesseract is available
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
        Extract text from a single page, using OCR if needed

        Args:
            page: PyMuPDF page object
            page_num: Page number (1-indexed)

        Returns:
            Dictionary with page text and metadata
        """
        # Try native text extraction first
        text = page.get_text()
        blocks = page.get_text("dict")["blocks"]

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

            # Extract text and calculate average confidence
            text_parts = []
            confidences = []

            for i, word in enumerate(ocr_data['text']):
                if word.strip():
                    text_parts.append(word)
                    conf = int(ocr_data['conf'][i])
                    if conf > 0:
                        confidences.append(conf)

            text = ' '.join(text_parts)
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
