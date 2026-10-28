"""Residue tests: PII must not survive in image pixels, not just on screen.

PyMuPDF's PDF_REDACT_IMAGE_PIXELS blanks the covered image pixels to WHITE and
draws the black box as a vector on top, so "blanked" here means the image
region is uniformly white (mean luminance 255), not dark. A rendered page
would be black either way, which is why these tests read the stored image.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

from unittest.mock import patch

import pytest

import fitz

from redactor import PDFRedactor, RedactionItem, _pad_redaction_rect
from security_fixtures import (
    text_png, make_searchable_scan_pdf, mean_luminance,
    make_image_only_pdf, image_sha256s, ocr_words_for,
)

# Page is 595x842pt; the 1240x1754 image maps at ~0.48 pt/px.
SX, SY = 595 / 1240, 842 / 1754
# Hidden text is 12pt; the drawn name is 24px (about 11.6pt) so the two line up.
NAME_RECT = fitz.Rect(140 * SX, 890 * SY, 700 * SX, 970 * SY)   # hidden-text box
# Image area that sits wholly inside the redaction rectangle for the name.
NAME_PIXELS = fitz.Rect(150 * SX, 895 * SY, 250 * SX, 921 * SY)
HEADER_RECT = fitz.Rect(100 * SX, 60 * SY, 600 * SX, 130 * SY)
BODY_RECT = fitz.Rect(150 * SX, 1300 * SY, 600 * SX, 1400 * SY)


def _scan_png(name, at, extra=None):
    from PIL import Image, ImageDraw, ImageFont
    import io
    img = Image.open(io.BytesIO(text_png(name, at=at, font_size=24)))
    if extra:
        font = ImageFont.load_default(size=48)
        ImageDraw.Draw(img).text(extra[1], extra[0], fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _redact(src, out, items, **kw):
    # Stage 2's OCR finds nothing, so only the text-layer path can blank pixels.
    with patch("redactor.pytesseract.image_to_data",
               return_value={'text': [], 'left': [], 'top': [], 'width': [],
                             'height': [], 'conf': []}):
        PDFRedactor().redact_pdf(src, out, items, **kw)


class TestTextLayerImagePixels:
    def test_name_pixels_blanked_when_ocr_misses(self, tmp_path):
        src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
        make_searchable_scan_pdf(src, text_png("Joe Bloggs", at=(150, 900), font_size=24),
                                 "Joe Bloggs", NAME_RECT)
        assert mean_luminance(src, 0, NAME_PIXELS) < 240
        _redact(src, out, [RedactionItem(page_num=1, text="Joe Bloggs")])
        assert mean_luminance(out, 0, NAME_PIXELS) > 254

    def test_header_zone_pixels_blanked(self, tmp_path):
        src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
        make_searchable_scan_pdf(src, text_png("Dummy School", at=(150, 80)),
                                 "x", fitz.Rect(50, 300, 200, 330))
        assert mean_luminance(src, 0, HEADER_RECT) < 250
        _redact(src, out, [], redact_header_footer=True)
        assert mean_luminance(out, 0, HEADER_RECT) > 254

    def test_rotated_scan_name_pixels_blanked(self, tmp_path):
        src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
        png = _scan_png("Joe Bloggs", (150, 900), extra=("Body text here", (150, 1320)))
        make_searchable_scan_pdf(src, png, "Joe Bloggs", NAME_RECT, rotate=90)
        _redact(src, out, [RedactionItem(page_num=1, text="Joe Bloggs")])
        assert mean_luminance(src, 0, NAME_PIXELS) < 240
        assert mean_luminance(out, 0, NAME_PIXELS) > 254
        assert mean_luminance(src, 0, BODY_RECT) < 250
        # and an untouched blank region stays white
        assert mean_luminance(out, 0, fitz.Rect(300, 600, 500, 700)) > 200
        # and the body text is pixel-identical to the source
        assert mean_luminance(out, 0, BODY_RECT) == mean_luminance(src, 0, BODY_RECT)

    def test_shared_image_other_page_untouched(self, tmp_path):
        src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
        doc = fitz.open()
        png = text_png("Joe Bloggs", at=(150, 900), font_size=24)
        p1 = doc.new_page()
        xref = p1.insert_image(p1.rect, stream=png)
        p1.insert_textbox(NAME_RECT, "Joe Bloggs", fontsize=12, render_mode=3)
        p2 = doc.new_page()
        p2.insert_image(p2.rect, stream=png, xref=xref)
        doc.save(str(src)); doc.close()

        _redact(src, out, [RedactionItem(page_num=1, text="Joe Bloggs")])

        def render(path, idx):
            d = fitz.open(str(path))
            try:
                return d[idx].get_pixmap(dpi=72)
            finally:
                d.close()
        before, after = render(src, 1), render(out, 1)
        assert before.samples == after.samples
        # page 1 itself is blanked at the name
        assert mean_luminance(out, 0, NAME_PIXELS) > 254


class TestPageReplacement:
    """A rebuilt scanned page must not keep the original scan in its resources."""

    # OCR coordinates are in 300 DPI render pixels (A4 page = 2480x3508).
    NAME_BOX = (300, 1800, 700, 60)

    def _scan(self, tmp_path, pages=1, share=False):
        src = tmp_path / "scan.pdf"
        make_image_only_pdf(src, text_png("Joe Bloggs", at=(150, 900)),
                            pages=pages, share_resources=share)
        return src, tmp_path / "out.pdf"

    def test_original_scan_not_in_output(self, tmp_path):
        src, out = self._scan(tmp_path)
        orig = image_sha256s(src)
        with patch("redactor.pytesseract.image_to_data",
                   return_value=ocr_words_for("Joe Bloggs", self.NAME_BOX)):
            ok, _ = PDFRedactor().redact_pdf(
                src, out, [RedactionItem(page_num=1, text="Joe Bloggs")])
        assert ok
        assert orig.isdisjoint(image_sha256s(out))

    def test_zone_blanking_drops_original_scan(self, tmp_path):
        src, out = self._scan(tmp_path)
        orig = image_sha256s(src)
        with patch("redactor.pytesseract.image_to_data",
                   return_value=ocr_words_for("", self.NAME_BOX)):
            ok, _ = PDFRedactor().redact_pdf(src, out, [], redact_header_footer=True)
        assert ok
        assert orig.isdisjoint(image_sha256s(out))

    def test_shared_resources_other_page_keeps_its_image(self, tmp_path):
        src, out = self._scan(tmp_path, pages=2, share=True)
        calls = {"n": 0}

        def ocr(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return ocr_words_for("Joe Bloggs", self.NAME_BOX)
            return ocr_words_for("", self.NAME_BOX)

        with patch("redactor.pytesseract.image_to_data", side_effect=ocr):
            ok, _ = PDFRedactor().redact_pdf(
                src, out, [RedactionItem(page_num=1, text="Joe Bloggs")])
        assert ok
        text_area = fitz.Rect(150 * 595 / 1240, 895 * 842 / 1754,
                              700 * 595 / 1240, 960 * 842 / 1754)
        assert mean_luminance(out, 1, text_area) < 250


# Lower half of a 48px name drawn at (150, 900): below the 12pt hidden-text
# line, so the text-layer redaction does not blank it.
GLYPH_TAIL = fitz.Rect(150 * SX, 922 * SY, 400 * SX, 950 * SY)


def _tesseract_available():
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _partial_glyph_output(tmp_path):
    """Searchable scan whose drawn name (48px) is taller AND wider than its
    12pt hidden text, redacted with Stage 2 OCR patched to miss and the
    widened image pass switched off, so glyph residue is guaranteed. This
    is the verifier's input, not a picture of what redact_pdf now ships."""
    src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
    make_searchable_scan_pdf(src, text_png("Joe Bloggs", at=(150, 900), font_size=48),
                             "Joe Bloggs", NAME_RECT)
    with patch.object(PDFRedactor, "_blank_image_band", lambda *a: None):
        _redact(src, out, [RedactionItem(page_num=1, text="Joe Bloggs")])
    return out


def _tall_glyph_png():
    """The name drawn at the width of its 12pt hidden text, then stretched to
    about 1.3x the redaction box's height and centred on it: printed glyphs
    taller than the OCR layer's text box, as on a real searchable scan.
    Returns (png bytes, ink box in page points)."""
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(text_png("Joe Bloggs", at=(150, 900), font_size=23))).convert("L")
    ink = Image.eval(img, lambda v: 255 - v).getbbox()
    band = img.crop((0, ink[1], img.width, ink[3]))
    band = band.resize((band.width, int(band.height * 1.55)))
    tall = Image.new("L", img.size, 255)
    tall.paste(band, (0, 907 - band.height // 2))   # 907px = hidden box centre
    x0, y0, x1, y1 = Image.eval(tall, lambda v: 255 - v).getbbox()
    buf = io.BytesIO()
    tall.save(buf, format="PNG")
    return buf.getvalue(), fitz.Rect(x0 * SX, y0 * SY, x1 * SX, y1 * SY)


def _tall_glyph_output(tmp_path, rotate=0, redact=_redact):
    src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
    png, ink = _tall_glyph_png()
    make_searchable_scan_pdf(src, png, "Joe Bloggs", NAME_RECT, rotate=rotate)
    # Precondition: the glyphs reach beyond the padded hidden-text box, both
    # above and below, so the first pass alone leaves tops and tails.
    box = _pad_redaction_rect(fitz.open(str(src))[0].search_for("Joe Bloggs")[0])
    assert ink.y0 < box.y0 - 1 and ink.y1 > box.y1 + 1
    assert mean_luminance(src, 0, ink) < 240
    redact(src, out, [RedactionItem(page_num=1, text="Joe Bloggs")])
    return out, ink


class TestResidueVerifier:
    """verify_no_hidden_residue reads the layers a page render cannot show."""

    def _ocr(self, text):
        return patch("redactor.pytesseract.image_to_string", return_value=text)

    def _verify(self, path, texts, ocr_text=""):
        with self._ocr(ocr_text):
            return PDFRedactor().verify_no_hidden_residue(path, texts)

    def test_flags_unredacted_image_bytes(self, tmp_path):
        pdf = tmp_path / "boxed.pdf"
        make_image_only_pdf(pdf, text_png("Joe Bloggs", at=(150, 900)))
        doc = fitz.open(str(pdf))
        doc[0].draw_rect(NAME_RECT, color=(0, 0, 0), fill=(0, 0, 0))
        doc.saveIncr()
        doc.close()

        clean, failures = self._verify(pdf, ["Joe Bloggs"], "Joe Bloggs")
        assert clean is False
        assert len(failures) == 1
        assert "image" in failures[0]

    def test_flags_info_key(self, tmp_path):
        pdf = tmp_path / "info.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.set_metadata({"author": "Joe Bloggs"})
        doc.save(str(pdf))
        doc.close()

        clean, failures = self._verify(pdf, ["Joe Bloggs"])
        assert clean is False
        assert len(failures) == 1
        assert "Author" in failures[0]
        # the message names the key, never the value
        assert "Bloggs" not in failures[0]

    def test_mupdf_producer_alone_is_not_flagged(self, tmp_path):
        pdf = tmp_path / "producer.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.set_metadata({"producer": "MuPDF 1.27.2", "title": ""})
        doc.save(str(pdf))
        doc.close()

        assert self._verify(pdf, ["Joe Bloggs"]) == (True, [])

    def _catalog_info(self, tmp_path, info):
        pdf = tmp_path / "catalog_info.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.save(str(pdf))
        doc.close()
        doc = fitz.open(str(pdf))
        doc.xref_set_key(doc.pdf_catalog(), "Info", info)
        doc.saveIncr()
        doc.close()
        return pdf

    def test_flags_catalog_info_key(self, tmp_path):
        """MuPDF writes /Info inside the catalog, not the trailer, so that
        is where a leftover value would sit."""
        pdf = self._catalog_info(tmp_path, "<</StudentName(Joe Bloggs)/Producer(MuPDF 1.27.2)>>")

        clean, failures = self._verify(pdf, ["Joe Bloggs"])
        assert clean is False
        assert len(failures) == 1
        assert "StudentName" in failures[0]
        assert "Bloggs" not in failures[0]

    def test_catalog_info_mupdf_producer_alone_is_not_flagged(self, tmp_path):
        pdf = self._catalog_info(tmp_path, "<</Producer(MuPDF 1.27.2)>>")

        assert self._verify(pdf, ["Joe Bloggs"]) == (True, [])

    def test_real_redact_output_catalog_info_passes(self, tmp_path):
        src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "Student Joe Bloggs")
        doc.set_metadata({"author": "Joe Bloggs", "producer": "Word"})
        doc.save(str(src))
        doc.close()
        ok, _ = PDFRedactor().redact_pdf(src, out, [RedactionItem(page_num=1, text="Joe Bloggs")])
        assert ok
        # Precondition: the output really carries a catalog /Info, so this
        # test exercises the new branch rather than passing vacuously.
        doc = fitz.open(str(out))
        assert doc.xref_get_key(doc.pdf_catalog(), "Info")[0] == "dict"
        doc.close()

        assert self._verify(out, ["Joe Bloggs"]) == (True, [])

    def test_flags_file_attachment(self, tmp_path):
        pdf = tmp_path / "attach.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.add_file_annot(fitz.Point(72, 72), b"Joe Bloggs", "notes.txt")
        doc.save(str(pdf))
        doc.close()

        clean, failures = self._verify(pdf, ["Joe Bloggs"])
        assert clean is False
        assert len(failures) == 1
        assert "attach" in failures[0].lower()

    def test_flags_thumbnail(self, tmp_path):
        pdf = tmp_path / "thumb.pdf"
        doc = fitz.open()
        page = doc.new_page()
        thumb = doc.get_new_xref()
        doc.update_object(thumb, "<</Width 1/Height 1/BitsPerComponent 8"
                                 "/ColorSpace/DeviceGray>>")
        doc.update_stream(thumb, b"\x00")
        doc.xref_set_key(page.xref, "Thumb", f"{thumb} 0 R")
        doc.save(str(pdf))
        doc.close()

        clean, failures = self._verify(pdf, ["Joe Bloggs"])
        assert clean is False
        assert len(failures) == 1
        assert "thumbnail" in failures[0].lower()

    def test_clean_output_passes(self, tmp_path):
        src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
        make_searchable_scan_pdf(src, text_png("Joe Bloggs", at=(150, 900), font_size=24),
                                 "Joe Bloggs", NAME_RECT)
        doc = fitz.open(str(src))
        doc.set_metadata({"author": "Joe Bloggs", "producer": "Word"})
        doc.saveIncr()
        doc.close()
        _redact(src, out, [RedactionItem(page_num=1, text="Joe Bloggs")])

        assert self._verify(out, ["Joe Bloggs"]) == (True, [])

    def test_lowercase_common_word_not_flagged(self, tmp_path):
        # A text-layer page, so the image really is OCR'd (a lone image on a
        # page with no text is left to the render check).
        pdf = tmp_path / "young.pdf"
        make_searchable_scan_pdf(pdf, text_png("young people", at=(150, 900), font_size=24),
                                 "young people", NAME_RECT)

        assert self._verify(pdf, ["Young"], "young people") == (True, [])

    def test_tesseract_missing_quarantines(self, tmp_path):
        import pytesseract
        pdf = tmp_path / "scan.pdf"
        make_searchable_scan_pdf(pdf, text_png("Joe Bloggs", at=(150, 900), font_size=24),
                                 "Joe Bloggs", NAME_RECT)

        with patch("redactor.pytesseract.image_to_string",
                   side_effect=pytesseract.TesseractNotFoundError()):
            clean, failures = PDFRedactor().verify_no_hidden_residue(pdf, ["Joe Bloggs"])
        assert clean is False
        assert len(failures) == 1
        assert "image check" in failures[0].lower()

    def test_rebuilt_scan_page_image_not_reocrd(self, tmp_path):
        """A rebuilt image-only page holds one full-page image and nothing
        else. verify_redaction_ocr has just OCR'd exactly those pixels from
        the 300 DPI render, so OCRing the stored image again only costs time
        (about +45% on a 10-page scan)."""
        src, out = tmp_path / "scan.pdf", tmp_path / "out.pdf"
        make_image_only_pdf(src, text_png("Joe Bloggs", at=(150, 900)), pages=2)
        with patch("redactor.pytesseract.image_to_data",
                   return_value=ocr_words_for("Joe Bloggs", TestPageReplacement.NAME_BOX)):
            ok, _ = PDFRedactor().redact_pdf(
                src, out, [RedactionItem(page_num=1, text="Joe Bloggs"),
                           RedactionItem(page_num=2, text="Joe Bloggs")])
        assert ok

        with patch("redactor.pytesseract.image_to_string", return_value="") as ocr:
            assert PDFRedactor().verify_no_hidden_residue(out, ["Joe Bloggs"]) == (True, [])
        ocr.assert_not_called()

    def test_text_layer_page_images_still_checked(self, tmp_path):
        """Hidden residue lives on text-layer pages: the image's pixels can sit
        under a black box the render shows. Those images are always read."""
        pdf = tmp_path / "searchable.pdf"
        make_searchable_scan_pdf(pdf, text_png("Joe Bloggs", at=(150, 900), font_size=24),
                                 "Joe Bloggs", NAME_RECT)

        with patch("redactor.pytesseract.image_to_string", return_value="Joe Bloggs") as ocr:
            clean, failures = PDFRedactor().verify_no_hidden_residue(pdf, ["Joe Bloggs"])
        assert ocr.call_count == 1
        assert clean is False
        assert failures and "image" in failures[0]

    def test_image_only_page_with_two_images_still_checked(self, tmp_path):
        """With a second image on the page, one can hide the other in the
        render, so both are read."""
        pdf = tmp_path / "two.pdf"
        make_image_only_pdf(pdf, text_png("Joe Bloggs", at=(150, 900)))
        doc = fitz.open(str(pdf))
        doc[0].insert_image(fitz.Rect(72, 72, 272, 172), stream=text_png("Dummy School", at=(10, 10)))
        doc.saveIncr()
        doc.close()

        with patch("redactor.pytesseract.image_to_string", return_value="Joe Bloggs") as ocr:
            clean, _ = PDFRedactor().verify_no_hidden_residue(pdf, ["Joe Bloggs"])
        assert ocr.call_count == 2
        assert clean is False

    def test_flags_partial_glyphs_outside_hidden_box(self, tmp_path):
        """The drawn name is taller than its 12pt hidden-text line, so the
        text-layer redaction blanks only the top of the glyphs. If what is
        left is legible, this verifier is the backstop that catches it."""
        out = _partial_glyph_output(tmp_path)
        # Precondition: the lower half of the glyphs really is still in the
        # stored image. Without it this test would pass on any output that
        # holds an image, because the OCR mock returns the name regardless.
        assert mean_luminance(out, 0, GLYPH_TAIL) < 240

        clean, failures = self._verify(out, ["Joe Bloggs"], "Joe Bloggs")
        assert clean is False
        assert failures and "image" in failures[0]

    @pytest.mark.skipif(not _tesseract_available(), reason="Tesseract not installed")
    def test_real_tesseract_partial_glyphs_gone(self, tmp_path):
        """No mocking at all: real Tesseract in Stage 2 and in the verifier.
        Glyphs taller than their hidden text used to leave legible tops and
        tails that this verifier quarantined; the widened image pass
        (_blank_image_band) now blanks them, so the output is clean."""
        out, _ = _tall_glyph_output(
            tmp_path, redact=lambda s, o, i: PDFRedactor().redact_pdf(s, o, i))

        assert PDFRedactor().verify_no_hidden_residue(out, ["Joe Bloggs"]) == (True, [])


class TestWidenedImageBlanking:
    """Second pass: image pixels are blanked over a wider band than the text
    redaction, without touching text on neighbouring lines (rule 11a)."""

    def test_tall_glyphs_blanked_beyond_hidden_box(self, tmp_path):
        out, ink = _tall_glyph_output(tmp_path)
        assert mean_luminance(out, 0, ink) > 254

    def test_tall_glyphs_blanked_on_rotated_page(self, tmp_path):
        out, ink = _tall_glyph_output(tmp_path, rotate=90)
        assert mean_luminance(out, 0, ink) > 254

    @pytest.mark.parametrize("with_image", [False, True])
    def test_neighbour_text_line_survives(self, tmp_path, with_image):
        src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
        doc = fitz.open()
        page = doc.new_page()
        if with_image:   # so the second pass really runs on this page
            page.insert_image(page.rect, stream=text_png("x", at=(1100, 1700)))
        page.insert_text((72, 100), "Joe Bloggs went home.", fontsize=11)
        page.insert_text((72, 112), "Her reading is at level 22.", fontsize=11)
        doc.save(str(src)); doc.close()

        _redact(src, out, [RedactionItem(page_num=1, text="Joe Bloggs")])

        text = fitz.open(str(out))[0].get_text()
        assert "Joe Bloggs" not in text
        assert "went home." in text
        assert "Her reading is at level 22." in text

    def test_no_second_pass_without_images(self, tmp_path):
        src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "Joe Bloggs went home.", fontsize=11)
        doc.save(str(src)); doc.close()

        real = fitz.Page.apply_redactions
        calls = []

        def spy(self, *a, **kw):
            calls.append(kw)
            return real(self, *a, **kw)

        with patch.object(fitz.Page, "apply_redactions", spy):
            _redact(src, out, [RedactionItem(page_num=1, text="Joe Bloggs")])
        assert len(calls) == 1

    @pytest.mark.parametrize("rotation", [0, 90, 180, 270])
    def test_band_widens_across_the_line_not_along_it(self, rotation):
        """The extra band reaches above and below the line AS DISPLAYED.

        Annotation rects are unrotated coordinates, so on a /Rotate 90 page
        the line runs along unrotated y. Padding unrotated y blanked 20% of
        the name's length into the next word and only 2pt across the line,
        leaving the descenders the band exists to remove."""
        import io
        from PIL import Image
        doc = fitz.open()
        page = doc.new_page(width=600, height=800)
        buf = io.BytesIO()
        Image.new("L", (600, 800), 0).save(buf, "PNG")   # black, 1px per pt
        page.insert_image(page.rect, stream=buf.getvalue())
        page.set_rotation(rotation)
        page.insert_text(fitz.Point(100, 300) * page.derotation_matrix,
                         "Billy Bob here", fontsize=12, rotate=rotation)
        hit = page.search_for("Billy Bob")[0]
        page.add_redact_annot(hit)
        rects = [a.rect for a in page.annots(types=[fitz.PDF_ANNOT_REDACT])]
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
        PDFRedactor()._blank_image_band(page, rects)

        img = Image.open(io.BytesIO(
            doc.extract_image(page.get_images(full=True)[0][0])["image"])).convert("L")
        shown = hit * page.rotation_matrix            # the name as displayed
        white = [fitz.Point(x + 0.5, y + 0.5) * page.rotation_matrix
                 for x in range(img.width) for y in range(img.height)
                 if img.getpixel((x, y)) > 128]
        xs = [p.x for p in white]
        ys = [p.y for p in white]
        # Across the line: at least most of the 20% band above and below.
        assert min(ys) <= shown.y0 - 0.15 * shown.height
        assert max(ys) >= shown.y1 + 0.15 * shown.height
        # Along the line: no more than a few points past either end.
        assert min(xs) >= shown.x0 - 4
        assert max(xs) <= shown.x1 + 4

    def test_second_pass_draws_no_extra_box(self, tmp_path):
        """The widened band blanks image pixels only: the page's vector
        drawings are the first pass's black boxes and nothing more."""
        out, _ = _tall_glyph_output(tmp_path)
        page = fitz.open(str(out))[0]
        fills = [d for d in page.get_drawings() if d.get("fill") is not None]
        assert len(fills) == 1


# A realistic single-spaced searchable scan: 300 DPI, 12pt text on a 13.8pt
# line pitch, each line with a correctly sized 12pt invisible text layer.
SCAN_DPI_SCALE = 300 / 72
SCAN_LINES = ["Her reading improved over the term.",
              "Joe Bloggs went home early today.",
              "Maths results were at level 22 now."]
SCAN_BASELINES = [200, 213.8, 227.6]


def _single_spaced_scan(path):
    from PIL import Image, ImageDraw, ImageFont
    import io
    s = SCAN_DPI_SCALE
    img = Image.new("L", (int(595 * s), int(842 * s)), 255)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=int(12 * s))
    for line, base in zip(SCAN_LINES, SCAN_BASELINES):
        draw.text((72 * s, base * s), line, fill=0, font=font, anchor="ls")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(page.rect, stream=buf.getvalue())
    for line, base in zip(SCAN_LINES, SCAN_BASELINES):
        page.insert_text((72, base), line, fontsize=12, render_mode=3)
    doc.save(str(path))
    doc.close()


def _stored_image(path):
    from PIL import Image
    import io
    doc = fitz.open(str(path))
    try:
        xref = doc[0].get_images(full=True)[0][0]
        return Image.open(io.BytesIO(doc.extract_image(xref)["image"])).convert("L")
    finally:
        doc.close()


def _ink(img, box_pt):
    """Dark pixels in `box_pt` (page points)."""
    import numpy as np
    s = SCAN_DPI_SCALE
    crop = img.crop(tuple(int(v * s) for v in box_pt))
    return int((np.asarray(crop) < 128).sum())


class TestSingleSpacedScan:
    """The widened band must not eat into the scan lines above and below."""

    def _run(self, tmp_path):
        src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
        _single_spaced_scan(src)
        _redact(src, out, [RedactionItem(page_num=1, text="Joe Bloggs")])
        name = fitz.open(str(src))[0].search_for("Joe Bloggs")[0]
        return _stored_image(src), _stored_image(out), name

    @staticmethod
    def _line_box(i):
        base = SCAN_BASELINES[i]
        return (60, base - 12, 400, base + 4)

    def test_neighbour_lines_keep_their_ink(self, tmp_path):
        before, after, _ = self._run(tmp_path)
        for i in (0, 2):
            kept = _ink(after, self._line_box(i)) / _ink(before, self._line_box(i))
            assert kept >= 0.95, (i, kept)

    def test_name_descenders_blanked(self, tmp_path):
        """The "gg" descenders in Bloggs hang below the hidden-text box; the
        first pass alone leaves them, the widened band removes them."""
        before, after, name = self._run(tmp_path)
        base = SCAN_BASELINES[1]
        tails = (name.x0 + name.width * 0.4, base + 0.5, name.x1, base + 4)
        assert _ink(before, tails) > 100   # precondition: the descenders exist
        assert _ink(after, tails) == 0

    @pytest.mark.skipif(not _tesseract_available(), reason="Tesseract not installed")
    def test_real_tesseract_reads_neighbour_lines(self, tmp_path):
        import pytesseract
        _, after, _ = self._run(tmp_path)
        s = SCAN_DPI_SCALE
        for i in (0, 2):
            crop = after.crop(tuple(int(v * s) for v in self._line_box(i)))
            assert pytesseract.image_to_string(crop, config="--psm 7").strip() == SCAN_LINES[i]
