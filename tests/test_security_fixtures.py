import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import hashlib
import fitz
from security_fixtures import (
    text_png, make_image_only_pdf, make_searchable_scan_pdf,
    image_sha256s, mean_luminance, ocr_words_for,
)


def test_text_png_is_png():
    png = text_png("Billy Bob")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_searchable_scan_has_hidden_text(tmp_path):
    pdf = tmp_path / "scan.pdf"
    make_searchable_scan_pdf(pdf, text_png("Billy Bob"), "Billy Bob",
                             fitz.Rect(100, 100, 400, 140))
    doc = fitz.open(str(pdf))
    page = doc[0]
    assert "Billy Bob" in page.get_text()
    assert len(page.get_images()) == 1
    doc.close()


def test_image_sha256s_finds_inserted_png(tmp_path):
    pdf = tmp_path / "img.pdf"
    make_image_only_pdf(pdf, text_png("Joe Bloggs"))
    hashes = image_sha256s(pdf)
    assert len(hashes) == 1
    doc = fitz.open(str(pdf))
    xref = doc[0].get_images()[0][0]
    assert hashlib.sha256(doc.extract_image(xref)["image"]).hexdigest() in hashes
    doc.close()


def test_image_only_pages_and_shared_resources(tmp_path):
    pdf = tmp_path / "multi.pdf"
    make_image_only_pdf(pdf, text_png("x"), pages=3, share_resources=True)
    doc = fitz.open(str(pdf))
    assert len(doc) == 3
    assert all(not p.get_text().strip() for p in doc)
    res = {doc.xref_get_key(p.xref, "Resources") for p in doc}
    assert len(res) == 1 and next(iter(res))[0] == "xref"
    doc.close()


def test_mean_luminance_dark_inside_text_bright_outside(tmp_path):
    pdf = tmp_path / "lum.pdf"
    make_image_only_pdf(pdf, text_png("MMMMMMMM", at=(150, 900), font_size=96))
    doc = fitz.open(str(pdf)); r = doc[0].rect; doc.close()
    sx, sy = r.width / 1240, r.height / 1754
    text_rect = fitz.Rect(150 * sx, 900 * sy, 700 * sx, 1000 * sy)
    blank_rect = fitz.Rect(10, 10, 100, 60)
    assert mean_luminance(pdf, 0, blank_rect) > 250
    assert mean_luminance(pdf, 0, text_rect) < mean_luminance(pdf, 0, blank_rect) - 20


def test_ocr_words_for_shape():
    d = ocr_words_for("Billy Bob", (100, 200, 300, 50))
    assert d["text"] == ["Billy", "Bob"]
    assert d["left"] == [100, 250] and d["width"] == [150, 150]
    assert d["top"] == [200, 200] and d["height"] == [50, 50]
    assert set(d) >= {"text", "left", "top", "width", "height", "conf"}


def test_mean_luminance_ignores_page_rotation(tmp_path):
    png = text_png("MMMMMMMM", at=(150, 900), font_size=96)
    flat, turned = tmp_path / "flat.pdf", tmp_path / "turned.pdf"
    rect = fitz.Rect(150 * 595 / 1240, 900 * 842 / 1754,
                     700 * 595 / 1240, 1000 * 842 / 1754)
    make_searchable_scan_pdf(flat, png, "x", fitz.Rect(50, 50, 200, 80))
    make_searchable_scan_pdf(turned, png, "x", fitz.Rect(50, 50, 200, 80), rotate=90)
    assert abs(mean_luminance(flat, 0, rect) - mean_luminance(turned, 0, rect)) < 1
    assert mean_luminance(turned, 0, rect) < 200


def test_searchable_scan_rejects_text_that_does_not_fit(tmp_path):
    import pytest
    with pytest.raises(AssertionError):
        make_searchable_scan_pdf(tmp_path / "x.pdf", text_png("a"),
                                 "word " * 200, fitz.Rect(10, 10, 40, 20))
