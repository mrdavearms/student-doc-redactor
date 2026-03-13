import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import pytest
import fitz
import numpy as np
from PIL import Image
from redactor import PDFRedactor


def _make_pil_image(width, height, ink_ratio=0.05):
    """Create a synthetic image with a controlled ink ratio.

    Generates a mostly-white image with a horizontal dark stroke
    in the middle to simulate a signature's pixel distribution.
    """
    img = Image.new("RGB", (width, height), (255, 255, 255))
    if ink_ratio > 0:
        # Draw dark pixels to reach approximately the target ink ratio
        pixels = np.array(img)
        total = width * height
        dark_count = int(total * ink_ratio)
        # Fill a horizontal band in the middle
        band_height = max(1, dark_count // width)
        y_start = height // 2 - band_height // 2
        y_end = min(height, y_start + band_height)
        pixels[y_start:y_end, :] = (30, 30, 30)
        img = Image.fromarray(pixels)
    return img


class TestIsLikelySignature:
    """Unit tests for the _is_likely_signature() heuristic."""

    def setup_method(self):
        self.redactor = PDFRedactor()

    def _rect(self, width, height):
        """Create a fitz.Rect with the given dimensions starting at (36, 100)."""
        return fitz.Rect(36, 100, 36 + width, 100 + height)

    # ── Positive cases: should detect as signature ──

    def test_typical_signature_detected(self):
        """A 302x56 image at 114pt wide with 9% ink — matches real SLD report signature."""
        img = _make_pil_image(302, 56, ink_ratio=0.09)
        rect = self._rect(114, 21)
        assert self.redactor._is_likely_signature(img, rect) is True

    def test_wide_thin_signature(self):
        """Very wide, thin signature (aspect 10:1) should be detected."""
        img = _make_pil_image(500, 50, ink_ratio=0.05)
        rect = self._rect(200, 20)
        assert self.redactor._is_likely_signature(img, rect) is True

    def test_signature_with_low_ink(self):
        """Faint signature with only 2% ink coverage."""
        img = _make_pil_image(300, 80, ink_ratio=0.02)
        rect = self._rect(150, 40)
        assert self.redactor._is_likely_signature(img, rect) is True

    def test_borderline_aspect_ratio(self):
        """Aspect ratio exactly at 2.0 boundary should still pass."""
        img = _make_pil_image(200, 100, ink_ratio=0.10)
        rect = self._rect(100, 50)
        assert self.redactor._is_likely_signature(img, rect) is True

    # ── Negative cases: should NOT detect as signature ──

    def test_letterhead_rejected(self):
        """842x470 image at 420pt wide — letterhead/banner, not a signature."""
        img = _make_pil_image(842, 470, ink_ratio=0.10)
        rect = self._rect(420, 176)
        assert self.redactor._is_likely_signature(img, rect) is False

    def test_square_icon_rejected(self):
        """39x38 icon at 29pt — checkbox/bullet, aspect ~1.0."""
        img = _make_pil_image(39, 38, ink_ratio=0.15)
        rect = self._rect(29, 29)
        assert self.redactor._is_likely_signature(img, rect) is False

    def test_full_page_scan_rejected(self):
        """2482x3510 full-page scan image — portrait aspect, way too large."""
        img = _make_pil_image(2482, 3510, ink_ratio=0.10)
        rect = self._rect(596, 842)
        assert self.redactor._is_likely_signature(img, rect) is False

    def test_photo_high_ink_rejected(self):
        """Wide image but with 50% ink coverage — a photo, not a signature."""
        img = _make_pil_image(400, 100, ink_ratio=0.50)
        rect = self._rect(200, 50)
        assert self.redactor._is_likely_signature(img, rect) is False

    def test_tall_image_rejected(self):
        """Tall narrow image (aspect < 2) — not a signature."""
        img = _make_pil_image(100, 200, ink_ratio=0.05)
        rect = self._rect(50, 100)
        assert self.redactor._is_likely_signature(img, rect) is False

    def test_tiny_icon_rejected(self):
        """Very small image (width < 50px) — too small to be a signature."""
        img = _make_pil_image(30, 10, ink_ratio=0.05)
        rect = self._rect(15, 5)
        assert self.redactor._is_likely_signature(img, rect) is False

    def test_wide_banner_too_large_on_page(self):
        """Wide but physically large on page (> 250pt) — a banner, not a signature."""
        img = _make_pil_image(600, 100, ink_ratio=0.08)
        rect = self._rect(300, 50)
        assert self.redactor._is_likely_signature(img, rect) is False

    def test_zero_height_image_rejected(self):
        """Edge case: zero-height image should not crash."""
        img = _make_pil_image(100, 1, ink_ratio=0.0)
        # 1px height, aspect 100:1, but guard against division issues
        rect = self._rect(50, 1)
        # Should not crash — may or may not match depending on thresholds
        result = self.redactor._is_likely_signature(img, rect)
        assert isinstance(result, bool)


class TestRedactSignatureImages:
    """Integration tests for _redact_signature_images() on in-memory PDFs."""

    def setup_method(self):
        self.redactor = PDFRedactor()

    def test_signature_image_is_replaced_with_black(self):
        """A signature-like image embedded in a PDF page should be blacked out."""
        doc = fitz.open()
        page = doc.new_page()

        # Create a signature-like image (wide, sparse ink)
        sig_img = _make_pil_image(300, 60, ink_ratio=0.08)
        buf = __import__('io').BytesIO()
        sig_img.save(buf, format="PNG")
        buf.seek(0)

        # Insert it small on the page (rect width < 250pt)
        page.insert_image(fitz.Rect(36, 150, 150, 173), stream=buf.read())

        count = self.redactor._redact_signature_images(page)
        assert count == 1

        # Verify the image was replaced (extract and check it's all black)
        images = page.get_images(full=True)
        assert len(images) >= 1
        xref = images[0][0]
        replaced = doc.extract_image(xref)
        replaced_img = Image.open(__import__('io').BytesIO(replaced['image'])).convert('RGB')
        arr = np.array(replaced_img)
        # All pixels should be black (0, 0, 0)
        assert arr.max() == 0, "Replaced image should be entirely black"

        doc.close()

    def test_non_signature_image_is_not_replaced(self):
        """A square icon image should not be affected."""
        doc = fitz.open()
        page = doc.new_page()

        # Create a square icon (aspect ~1.0)
        icon_img = _make_pil_image(40, 40, ink_ratio=0.15)
        buf = __import__('io').BytesIO()
        icon_img.save(buf, format="PNG")
        buf.seek(0)

        page.insert_image(fitz.Rect(100, 100, 130, 130), stream=buf.read())

        count = self.redactor._redact_signature_images(page)
        assert count == 0

        doc.close()

    def test_page_with_no_images_returns_zero(self):
        """A text-only page should return 0."""
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "No images here.", fontsize=12)
        count = self.redactor._redact_signature_images(page)
        assert count == 0
        doc.close()

    def test_mixed_images_only_signature_redacted(self):
        """Page with both a signature and a non-signature image: only signature is redacted."""
        doc = fitz.open()
        page = doc.new_page()

        # Signature-like image
        sig_img = _make_pil_image(300, 60, ink_ratio=0.08)
        buf1 = __import__('io').BytesIO()
        sig_img.save(buf1, format="PNG")
        buf1.seek(0)
        page.insert_image(fitz.Rect(36, 150, 150, 173), stream=buf1.read())

        # Square icon
        icon_img = _make_pil_image(40, 40, ink_ratio=0.15)
        buf2 = __import__('io').BytesIO()
        icon_img.save(buf2, format="PNG")
        buf2.seek(0)
        page.insert_image(fitz.Rect(200, 200, 230, 230), stream=buf2.read())

        count = self.redactor._redact_signature_images(page)
        assert count == 1, "Only the signature image should be redacted"
        doc.close()
