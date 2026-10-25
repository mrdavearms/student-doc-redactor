"""Synthetic-PDF fixtures for the redaction residue tests.

Dummy data only: callers pass names such as "Joe Bloggs" or "Billy Bob".
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import hashlib
import io
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont, ImageStat


def text_png(text: str, width: int = 1240, height: int = 1754,
             at: tuple = (150, 900), font_size: int = 48) -> bytes:
    """White PNG with black text drawn at pixel position `at`."""
    img = Image.new("RGB", (width, height), "white")
    font = ImageFont.load_default(size=font_size)
    ImageDraw.Draw(img).text(at, text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_image_only_pdf(path: Path, png: bytes, pages: int = 1,
                        share_resources: bool = False) -> None:
    """Pages holding only the PNG at page.rect. With share_resources, every
    page's /Resources points at one indirect dictionary."""
    doc = fitz.open()
    image_xref = None
    for _ in range(pages):
        page = doc.new_page()
        if image_xref is None:
            image_xref = page.insert_image(page.rect, stream=png)
        else:
            page.insert_image(page.rect, stream=png, xref=image_xref)
    if share_resources:
        names = {}
        for page in doc:
            for img in page.get_images(full=True):
                names[img[7]] = img[0]
        shared = doc.get_new_xref()
        body = " ".join(f"/{n} {x} 0 R" for n, x in names.items())
        doc.update_object(shared, f"<</XObject<<{body}>>>>")
        for page in doc:
            doc.xref_set_key(page.xref, "Resources", f"{shared} 0 R")
    doc.save(str(path))
    doc.close()


def make_searchable_scan_pdf(path: Path, png: bytes, hidden_text: str,
                             rect: fitz.Rect, rotate: int = 0) -> None:
    """Full-page image plus an invisible text layer (render_mode 3) in rect."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(page.rect, stream=png)
    written = page.insert_textbox(rect, hidden_text, fontsize=12, render_mode=3)
    assert written >= 0, "hidden text did not fit in rect"
    if rotate:
        page.set_rotation(rotate)
    doc.save(str(path))
    doc.close()


def image_sha256s(pdf_path: Path) -> set:
    """SHA-256 of the stored bytes of every image object in the file."""
    doc = fitz.open(str(pdf_path))
    try:
        hashes = set()
        for xref in range(1, doc.xref_length()):
            if doc.xref_get_key(xref, "Subtype")[1] == "/Image":
                data = doc.extract_image(xref)["image"]
                hashes.add(hashlib.sha256(data).hexdigest())
        return hashes
    finally:
        doc.close()


def mean_luminance(pdf_path: Path, page_index: int, rect: fitz.Rect) -> float:
    """Mean 0-255 grey of the page's largest image (by pixel area) under `rect`.

    `rect` is in unrotated page coordinates, the space the image is stored in.
    It is mapped linearly onto the image's pixel size using the unrotated
    page size (page.mediabox), so a /Rotate page gives the same answer as an
    unrotated one.
    """
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_index]
        best = max(page.get_images(full=True), key=lambda i: i[2] * i[3])
        info = doc.extract_image(best[0])
        img = Image.open(io.BytesIO(info["image"])).convert("L")
        sx = img.width / page.mediabox.width
        sy = img.height / page.mediabox.height
        box = (int(rect.x0 * sx), int(rect.y0 * sy),
               max(int(rect.x1 * sx), int(rect.x0 * sx) + 1),
               max(int(rect.y1 * sy), int(rect.y0 * sy) + 1))
        crop = img.crop(box)
        return float(ImageStat.Stat(crop).mean[0])
    finally:
        doc.close()


def ocr_words_for(text: str, box: tuple) -> dict:
    """pytesseract.image_to_data DICT with one word per token, split evenly
    across box = (left, top, width, height)."""
    left, top, width, height = box
    words = text.split()
    each = width // max(len(words), 1)
    data = {'text': [], 'left': [], 'top': [], 'width': [], 'height': [], 'conf': []}
    for i, w in enumerate(words):
        data['text'].append(w)
        data['left'].append(left + i * each)
        data['top'].append(top)
        data['width'].append(each)
        data['height'].append(height)
        data['conf'].append(95)
    return data
