# Image-Embedded PII Redaction (Option A+) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** OCR every embedded image on every PDF page and black out any PII found in the image pixels, closing the gap where hybrid pages (text + images) leave image-embedded PII untouched.

**Architecture:** After text-layer redaction completes on each page, a new pass iterates every embedded image via `page.get_images()`, extracts it with `doc.extract_image(xref)`, OCRs the pixels with pytesseract, draws opaque black rectangles over PII matches on the PIL image, and replaces the original with `page.replace_image(xref, stream=png_bytes)`. The OCR word-matching logic is extracted from `_redact_ocr_page()` into a shared helper so both full-page OCR and per-image OCR use identical matching rules.

**Tech Stack:** PyMuPDF (fitz), pytesseract, Pillow (PIL), pytest

---

## Background

### The Problem

`_is_image_only_page()` returns `False` for hybrid pages (pages with both text-layer words AND embedded images). Those pages route to text-layer-only redaction, leaving PII inside embedded images completely untouched.

Real example: Page 8 of `Joe Bloggs IEP S2 2025.docx (1).pdf` has an email screenshot embedded as a 1726x716 image containing student names, teacher names, and email addresses. All survived redaction.

### The Fix: Three-Stage Pipeline

For every page that has redaction items:

1. **Stage 1 — Text-layer redaction** (existing): `search_for()` + `add_redact_annot()` + `apply_redactions()` for pages with text layers. `_redact_ocr_page()` for image-only pages.
2. **Stage 2 — Per-image OCR** (NEW): Extract every embedded image on the page, OCR each one, black out PII matches in the image pixels, replace the image in the PDF.
3. **Stage 3 — Widget deletion** (existing): `_delete_pii_widgets()` removes form fields containing PII.

### Image Formats Encountered

| Format | Filter | Sample |
|--------|--------|--------|
| PNG | FlateDecode | IEP document logos and email screenshot |
| JPEG | DCTDecode | AA report page 1 |
| 1-bit grayscale | CCITTFaxDecode | AA report page 2 |

All three are handled correctly by `doc.extract_image()` → PIL → PNG → `page.replace_image()`. Verified in spike testing.

---

## Task 1: Extract OCR Word-Matching into a Shared Helper

### Why

`_redact_ocr_page()` contains ~50 lines of word-matching logic (lines 299-348) that the new per-image method needs to reuse identically. Extract it into `_match_and_redact_ocr_words()` so both callers share the same matching rules.

**Files:**
- Modify: `src/core/redactor.py` (extract method, update caller)
- Test: `tests/test_ocr_redaction.py` (all existing tests must still pass)

**Step 1: Write the test that proves the refactor is safe**

No new test needed here — the existing 12 tests in `TestRedactOcrPageMatching` and 2 tests in `TestRedactPdfRouting` cover the word-matching logic. We run them before and after the refactor to prove nothing changed.

```bash
source venv/bin/activate && pytest tests/test_ocr_redaction.py -v
```

Expected: all 19 tests PASS (baseline).

**Step 2: Extract `_match_and_redact_ocr_words()` from `_redact_ocr_page()`**

Add this new method to `PDFRedactor` in `src/core/redactor.py`, right before `_redact_ocr_page()` (insert at line 237):

```python
def _match_and_redact_ocr_words(
    self,
    draw: 'ImageDraw.Draw',
    ocr_words: list,
    items: list,
    padding: int = 4,
) -> int:
    """
    Match PII items against OCR word bounding boxes and draw black
    rectangles over matches on the provided ImageDraw canvas.

    Handles: single-word exact, possessives (straight/curly apostrophe),
    trailing punctuation, multi-word consecutive, email/URL substring,
    case-insensitive matching.

    Args:
        draw: PIL ImageDraw object to draw black rectangles on.
        ocr_words: List of (word_text, (x0, y0, x1, y1)) from OCR.
        items: RedactionItems whose .text to search for.
        padding: Pixel padding around each match rectangle.

    Returns:
        Number of PII word-groups redacted.
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
                ocr_clean = re.sub(r"[^\w'\u2019]", '', ocr_lower)
                if (
                    ocr_clean == pii_lower
                    or ocr_clean == pii_lower + "'s"
                    or ocr_clean == pii_lower + "\u2019s"
                    or ocr_clean.rstrip(".,;:!?") == pii_lower
                    or (not pii_lower.isalpha() and pii_lower in ocr_lower)
                ):
                    x0, y0, x1, y1 = pixel_bbox
                    draw.rectangle(
                        [x0 - padding, y0 - padding, x1 + padding, y1 + padding],
                        fill="black",
                    )
                    redacted_count += 1
        else:
            # Multi-word PII: find consecutive OCR words
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
```

**Step 3: Update `_redact_ocr_page()` to call the shared helper**

Replace lines 294-348 (the draw/matching block) inside `_redact_ocr_page()` with:

```python
        # Draw black rectangles directly on the PIL image (pixel space)
        draw = ImageDraw.Draw(img)
        redacted_count = self._match_and_redact_ocr_words(draw, ocr_words, items)
```

The `padding = 4` line and the entire for-loop block are deleted — they're now inside the helper.

**Step 4: Run tests to verify refactor is safe**

```bash
source venv/bin/activate && pytest tests/test_ocr_redaction.py -v
```

Expected: all 19 tests PASS (identical to baseline).

**Step 5: Commit**

```bash
git add src/core/redactor.py
git commit -m "refactor: extract OCR word-matching into shared _match_and_redact_ocr_words helper"
```

---

## Task 2: Write Failing Tests for `_redact_embedded_images()`

**Files:**
- Create tests in: `tests/test_ocr_redaction.py` (new `TestRedactEmbeddedImages` class)

**Step 1: Add helper to create a hybrid page (text + embedded image)**

Add this helper function near the top of `tests/test_ocr_redaction.py`, after `_make_image_pdf_with_text()`:

```python
def _make_hybrid_page(text_content="Some text", image_width=400, image_height=300):
    """
    Create a single-page PDF with BOTH native text AND an embedded image.

    This simulates the real-world case where a page has text-layer content
    (so _is_image_only_page returns False) but also has an embedded image
    that may contain PII (e.g. an email screenshot).

    Returns:
        (page, doc) tuple.
    """
    doc = fitz.open()
    page = doc.new_page()
    # Add native text layer
    page.insert_text((72, 100), text_content, fontsize=12)
    # Add an embedded image
    img = Image.new("RGB", (image_width, image_height), "white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    page.insert_image(fitz.Rect(50, 200, 50 + image_width // 2, 200 + image_height // 2), stream=buf.read())
    return page, doc
```

**Step 2: Write the failing test class**

Add a new test class `TestRedactEmbeddedImages` at the end of `tests/test_ocr_redaction.py`:

```python
# ---------------------------------------------------------------------------
# _redact_embedded_images tests (per-image OCR scanning)
# ---------------------------------------------------------------------------

class TestRedactEmbeddedImages:
    """
    Test the per-image OCR scanning that extracts each embedded image,
    OCRs it independently, and blacks out PII matches in the image pixels.
    """

    def setup_method(self):
        self.redactor = PDFRedactor()

    def _mock_ocr_data(self, words_with_boxes):
        """Build pytesseract.image_to_data DICT output."""
        data = {'text': [], 'left': [], 'top': [], 'width': [], 'height': [], 'conf': []}
        for word, x, y, w, h in words_with_boxes:
            data['text'].append(word)
            data['left'].append(x)
            data['top'].append(y)
            data['width'].append(w)
            data['height'].append(h)
            data['conf'].append(95)
        return data

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_finds_pii_in_embedded_image(self, mock_ocr, mock_tess_ver):
        """PII found inside an embedded image should be redacted."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("Joe", 100, 50, 80, 30),
            ("Bloggs", 200, 50, 80, 30),
        ])

        page, doc = _make_hybrid_page()
        items = [RedactionItem(page_num=1, text="Joe Bloggs")]
        count = self.redactor._redact_embedded_images(page, items)
        assert count >= 1
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_no_pii_returns_zero(self, mock_ocr, mock_tess_ver):
        """When no PII is found in any image, return 0."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("The", 50, 50, 50, 30),
            ("report", 120, 50, 100, 30),
        ])

        page, doc = _make_hybrid_page()
        items = [RedactionItem(page_num=1, text="Joe")]
        count = self.redactor._redact_embedded_images(page, items)
        assert count == 0
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_page_with_no_images_returns_zero(self, mock_ocr, mock_tess_ver):
        """A text-only page (no images) should return 0 immediately."""
        mock_tess_ver.return_value = '5.0'

        page, doc = _make_text_page("Hello world")
        items = [RedactionItem(page_num=1, text="Hello")]
        count = self.redactor._redact_embedded_images(page, items)
        assert count == 0
        # OCR should never be called — no images to scan
        mock_ocr.assert_not_called()
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_multiple_images_all_scanned(self, mock_ocr, mock_tess_ver):
        """Each embedded image should be OCR-scanned independently."""
        mock_tess_ver.return_value = '5.0'
        # First image has PII, second doesn't
        mock_ocr.side_effect = [
            self._mock_ocr_data([("Joe", 10, 10, 50, 20)]),
            self._mock_ocr_data([("nothing", 10, 10, 80, 20)]),
        ]

        # Create page with TWO images
        doc = fitz.open()
        page = doc.new_page()
        for i in range(2):
            img = Image.new("RGB", (200, 200), "white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            y_off = i * 250
            page.insert_image(fitz.Rect(50, 50 + y_off, 250, 250 + y_off), stream=buf.read())

        items = [RedactionItem(page_num=1, text="Joe")]
        count = self.redactor._redact_embedded_images(page, items)
        assert count == 1
        assert mock_ocr.call_count == 2  # Both images scanned
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_email_address_in_image(self, mock_ocr, mock_tess_ver):
        """Email addresses in images should be matched (substring match for special chars)."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("fred.bloggs@emaildomain.com", 10, 10, 400, 20),
        ])

        page, doc = _make_hybrid_page()
        items = [RedactionItem(page_num=1, text="fred.bloggs@emaildomain.com")]
        count = self.redactor._redact_embedded_images(page, items)
        assert count >= 1
        doc.close()

    @patch('redactor.pytesseract')
    def test_no_tesseract_returns_zero(self, mock_tess):
        """Graceful degradation when Tesseract is not available."""
        mock_tess.get_tesseract_version.side_effect = Exception("not installed")

        page, doc = _make_hybrid_page()
        items = [RedactionItem(page_num=1, text="Joe")]
        count = self.redactor._redact_embedded_images(page, items)
        assert count == 0
        doc.close()

    @patch('redactor.pytesseract.get_tesseract_version')
    @patch('redactor.pytesseract.image_to_data')
    def test_image_replaced_in_pdf(self, mock_ocr, mock_tess_ver):
        """After redaction, the image in the PDF should be replaced (different bytes)."""
        mock_tess_ver.return_value = '5.0'
        mock_ocr.return_value = self._mock_ocr_data([
            ("Joe", 100, 50, 80, 30),
        ])

        page, doc = _make_hybrid_page()

        # Get original image bytes
        images = page.get_images(full=True)
        assert len(images) >= 1
        orig_xref = images[0][0]
        orig_img_data = doc.extract_image(orig_xref)
        orig_bytes = orig_img_data['image']

        items = [RedactionItem(page_num=1, text="Joe")]
        count = self.redactor._redact_embedded_images(page, items)
        assert count >= 1

        # Image bytes should have changed (black rectangle drawn)
        new_img_data = doc.extract_image(orig_xref)
        new_bytes = new_img_data['image']
        assert new_bytes != orig_bytes
        doc.close()
```

**Step 3: Run tests to verify they fail**

```bash
source venv/bin/activate && pytest tests/test_ocr_redaction.py::TestRedactEmbeddedImages -v
```

Expected: FAIL with `AttributeError: 'PDFRedactor' object has no attribute '_redact_embedded_images'`

**Step 4: Commit the failing tests**

```bash
git add tests/test_ocr_redaction.py
git commit -m "test: add failing tests for _redact_embedded_images per-image OCR scanning"
```

---

## Task 3: Implement `_redact_embedded_images()`

**Files:**
- Modify: `src/core/redactor.py` (add new method)

**Step 1: Add `_redact_embedded_images()` method**

Insert this method in `src/core/redactor.py` inside the `PDFRedactor` class, right after the `_match_and_redact_ocr_words()` method (before `_redact_ocr_page()`):

```python
def _redact_embedded_images(self, page: fitz.Page, items: list) -> int:
    """
    OCR every embedded image on a page and black out PII matches
    in the image pixels. Replaces each modified image in the PDF.

    This catches PII inside embedded screenshots, scanned email
    printouts, logos with names, etc. — even on pages that have a
    normal text layer (hybrid pages).

    Args:
        page: PyMuPDF page object.
        items: RedactionItems whose .text to search for in images.

    Returns:
        Total number of PII word-groups redacted across all images.
    """
    images = page.get_images(full=True)
    if not images:
        return 0

    if not self._check_tesseract():
        return 0

    # Resolve Tesseract paths (same as _redact_ocr_page)
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
            continue  # Corrupted or unsupported image — skip

        if not img_dict or not img_dict.get('image'):
            continue

        img_bytes = img_dict['image']

        try:
            pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        except Exception:
            continue  # Can't decode image — skip

        # OCR the individual image
        ocr_data = pytesseract.image_to_data(
            pil_img, output_type=pytesseract.Output.DICT
        )

        # Build word list from OCR output
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

        # Draw black rectangles on PII matches
        draw = ImageDraw.Draw(pil_img)
        redacted_count = self._match_and_redact_ocr_words(
            draw, ocr_words, items
        )

        if redacted_count == 0:
            continue

        # Save modified image as PNG and replace in PDF
        out_buf = io.BytesIO()
        pil_img.save(out_buf, format="PNG")
        out_buf.seek(0)

        try:
            page.replace_image(xref, stream=out_buf.read())
        except Exception:
            continue  # replace_image failed — skip this image

        total_redacted += redacted_count

    return total_redacted
```

**Step 2: Run the new tests**

```bash
source venv/bin/activate && pytest tests/test_ocr_redaction.py::TestRedactEmbeddedImages -v
```

Expected: all 7 new tests PASS.

**Step 3: Run ALL tests to verify no regressions**

```bash
source venv/bin/activate && pytest tests/test_ocr_redaction.py -v
```

Expected: all 26 tests PASS (19 existing + 7 new).

**Step 4: Commit**

```bash
git add src/core/redactor.py
git commit -m "feat: add _redact_embedded_images for per-image OCR PII scanning"
```

---

## Task 4: Wire `_redact_embedded_images()` into `redact_pdf()` Pipeline

**Files:**
- Modify: `src/core/redactor.py:87-150` (the `redact_pdf` method)
- Test: `tests/test_ocr_redaction.py` (new routing tests)

**Step 1: Write the failing test**

Add to `TestRedactPdfRouting` class in `tests/test_ocr_redaction.py`:

```python
@patch.object(PDFRedactor, '_redact_embedded_images', return_value=2)
@patch.object(PDFRedactor, '_is_image_only_page', return_value=False)
def test_embedded_images_scanned_on_text_pages(self, mock_is_img, mock_embed_redact, tmp_path):
    """Text pages should ALSO have embedded images scanned for PII."""
    page, doc = _make_text_page("Joe attended school")
    input_pdf = tmp_path / "input.pdf"
    doc.save(str(input_pdf))
    doc.close()

    output_pdf = tmp_path / "output.pdf"
    items = [RedactionItem(page_num=1, text="Joe")]

    success, msg = self.redactor.redact_pdf(input_pdf, output_pdf, items)

    assert success is True
    mock_embed_redact.assert_called_once()

@patch.object(PDFRedactor, '_redact_embedded_images', return_value=0)
@patch.object(PDFRedactor, '_redact_ocr_page', return_value=1)
@patch.object(PDFRedactor, '_is_image_only_page', return_value=True)
def test_embedded_images_scanned_on_ocr_pages_too(self, mock_is_img, mock_ocr, mock_embed_redact, tmp_path):
    """Image-only pages should ALSO run per-image scanning after OCR page redaction."""
    doc = fitz.open()
    doc.new_page()
    input_pdf = tmp_path / "input.pdf"
    doc.save(str(input_pdf))
    doc.close()

    output_pdf = tmp_path / "output.pdf"
    items = [RedactionItem(page_num=1, text="Joe")]

    success, msg = self.redactor.redact_pdf(input_pdf, output_pdf, items)

    assert success is True
    mock_embed_redact.assert_called_once()
```

**Step 2: Run to verify they fail**

```bash
source venv/bin/activate && pytest tests/test_ocr_redaction.py::TestRedactPdfRouting -v
```

Expected: new tests FAIL (`_redact_embedded_images` never called).

**Step 3: Update `redact_pdf()` to call `_redact_embedded_images()`**

In `src/core/redactor.py`, modify the `redact_pdf()` method. Replace lines 110-138 with:

```python
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
                            self._redact_bbox(page, item.bbox)
                        else:
                            self._redact_text_search(page, item.text)

                    # Apply all redactions on this page
                    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

                # Stage 2: Scan every embedded image on this page for PII.
                # Runs on ALL pages — text-layer, image-only, and hybrid.
                # This catches PII in embedded screenshots, email printouts,
                # logos with names, etc. that text-layer redaction cannot reach.
                image_redacted_count += self._redact_embedded_images(page, items)

                # Stage 3: Delete form widgets whose values contain redacted PII.
                redacted_texts = [item.text.lower() for item in items]
                self._delete_pii_widgets(page, redacted_texts)
```

**Step 4: Run ALL tests**

```bash
source venv/bin/activate && pytest tests/test_ocr_redaction.py -v
```

Expected: all 28 tests PASS (19 original + 7 from Task 2 + 2 new routing tests).

**Step 5: Run the full test suite**

```bash
source venv/bin/activate && pytest tests/ -v
```

Expected: ~164 tests pass (159 existing + 5 pre-existing Tesseract failures in test_ocr_verification.py are unrelated).

**Step 6: Commit**

```bash
git add src/core/redactor.py tests/test_ocr_redaction.py
git commit -m "feat: wire _redact_embedded_images into redact_pdf three-stage pipeline"
```

---

## Task 5: Update CLAUDE.md Documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add new rule to Critical Non-Obvious Rules section**

Add after rule 11 (OCR pages cannot be automatically redacted):

```markdown
### 12. Every embedded image is OCR-scanned for PII (Stage 2)

After text-layer redaction, `_redact_embedded_images()` runs on every page. It extracts each embedded image via `doc.extract_image(xref)`, OCRs it with pytesseract, blacks out PII matches in the image pixels using PIL, and replaces the original via `page.replace_image(xref, stream=png_bytes)`. This catches PII in email screenshots, scanned documents, and even small logos. No image is too small to scan — there is no size threshold.

### 13. OCR word-matching logic is shared via `_match_and_redact_ocr_words()`

Both `_redact_ocr_page()` (full-page image-only OCR) and `_redact_embedded_images()` (per-image OCR) use the same matching helper. Any change to matching rules (possessives, punctuation, email substring, etc.) must be made in `_match_and_redact_ocr_words()` to affect both paths.
```

**Step 2: Update the Key Files table**

No change needed — `src/core/redactor.py` is already listed.

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add embedded image OCR scanning rules to CLAUDE.md"
```

---

## Summary of Changes

| File | Change |
|------|--------|
| `src/core/redactor.py` | New `_match_and_redact_ocr_words()` shared helper |
| `src/core/redactor.py` | New `_redact_embedded_images()` method |
| `src/core/redactor.py` | `_redact_ocr_page()` refactored to use shared helper |
| `src/core/redactor.py` | `redact_pdf()` updated with three-stage pipeline |
| `tests/test_ocr_redaction.py` | `_make_hybrid_page()` test helper |
| `tests/test_ocr_redaction.py` | 7 new tests in `TestRedactEmbeddedImages` |
| `tests/test_ocr_redaction.py` | 2 new routing tests in `TestRedactPdfRouting` |
| `CLAUDE.md` | Rules 12-13 added |
