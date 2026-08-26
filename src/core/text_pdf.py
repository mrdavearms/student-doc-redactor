"""
Text -> PDF renderer for the paste-text pathway.

Blackout output cannot simply be written into a PDF. PyMuPDF's built-in base-14
fonts are Latin-1 only and have NO glyph for U+2588, so a block run renders as
"??????" — wrong output rather than an error.

Instead each block run is laid out as a Latin-1 SENTINEL and then removed with a
redaction annotation, which paints the box and deletes the sentinel text in one
step. The PII was never placed in the PDF, so there is nothing under the boxes
either way.

The sentinel is chosen per render. search_for() cannot tell our sentinel from
the same characters occurring in the user's own text, so a hard-coded one would
black out real content — a maths report containing "XXXX", a table of "~~~~"
separators.
"""

import re

import fitz

MARGIN = 50
FONT_NAME = 'helv'
FONT_SIZE = 11
_A4 = fitz.paper_rect('a4')

# Latin-1 characters that render in the base-14 fonts and are rare in school
# reports. Order is preference order.
SENTINEL_CANDIDATES = ['¤', '¦', '¿', '~', '^', '¶', '§']
FALLBACK_SENTINEL = '[REMOVED]'

# A slab that cannot be laid out must not spin forever.
MAX_PAGES = 200


def choose_sentinel(text: str, width: int = 6) -> str:
    """
    A stand-in string guaranteed absent from `text`.

    Fixed repetition keeps every box the same width, which is what carries the
    fixed-width decision through from the text into the PDF.

    If every candidate character already occurs in `text`, fall back to the
    literal marker `[REMOVED]` -- but that marker gets no exemption from the
    same guarantee. When `[REMOVED]` itself also occurs in `text` (the user's
    own writing quotes the marker), it is extended with a growing numeric
    suffix (`[REMOVED0]`, `[REMOVED00]`, ...) until the result is absent. The
    search is bounded by len(text): a string longer than `text` can never
    occur as a substring of it, so trying suffix lengths up to len(text) + 1
    guarantees both termination and a collision-free result without an
    unbounded search.
    """
    for char in SENTINEL_CANDIDATES:
        if char not in text:
            return char * width

    if FALLBACK_SENTINEL not in text:
        return FALLBACK_SENTINEL

    for n in range(1, len(text) + 2):
        candidate = f'[REMOVED{"0" * n}]'
        if candidate not in text:
            return candidate

    # Unreachable: at n == len(text) + 1, len(candidate) > len(text), so it
    # cannot possibly occur as a substring of text.
    return f'[REMOVED{"0" * (len(text) + 1)}]'


def _page_rect() -> fitz.Rect:
    return fitz.Rect(MARGIN, MARGIN, _A4.width - MARGIN, _A4.height - MARGIN)


def _fits(text: str, rect: fitz.Rect) -> bool:
    """insert_textbox mutates the page, so probe on a throwaway document."""
    probe = fitz.open()
    page = probe.new_page(width=_A4.width, height=_A4.height)
    leftover = page.insert_textbox(
        rect, text, fontname=FONT_NAME, fontsize=FONT_SIZE)
    probe.close()
    return leftover >= 0


def _split_for_page(text: str, rect: fitz.Rect):
    """(what fits on one page, the remainder). Splits on whitespace."""
    if _fits(text, rect):
        return text, ''

    breaks = [m.end() for m in re.finditer(r'\s+', text)]
    if not breaks:
        breaks = [len(text)]

    lo, hi, best = 0, len(breaks) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if _fits(text[:breaks[mid]], rect):
            best = breaks[mid]
            lo = mid + 1
        else:
            hi = mid - 1

    if best is None:
        # A single unbroken token taller than a page. Hard-split rather than
        # loop forever producing empty pages.
        best = max(1, len(text) // 2)
    return text[:best], text[best:]


def _strip_metadata(doc: fitz.Document) -> None:
    doc.set_metadata({
        'author': '', 'title': '', 'subject': '', 'creator': '',
        'producer': '', 'keywords': '', 'creationDate': '', 'modDate': '',
    })
    doc.del_xml_metadata()


def render(text: str, out_path, block: str) -> None:
    """Lay `text` out as a PDF, turning each `block` run into a black box."""
    sentinel = choose_sentinel(text)
    laid_out = (text or '').replace(block, sentinel)

    doc = fitz.open()
    rect = _page_rect()
    remaining = laid_out
    try:
        while True:
            page = doc.new_page(width=_A4.width, height=_A4.height)
            chunk, remaining = _split_for_page(remaining, rect)
            page.insert_textbox(
                rect, chunk, fontname=FONT_NAME, fontsize=FONT_SIZE)
            if not remaining or doc.page_count >= MAX_PAGES:
                break

        for page in doc:
            for hit in page.search_for(sentinel):
                page.add_redact_annot(hit, fill=(0, 0, 0))
            # PDF_REDACT_IMAGE_NONE per CLAUDE.md rule 14. A generated text PDF
            # has no images, but the constant must not drift across the codebase.
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        _strip_metadata(doc)
        doc.save(str(out_path))
    finally:
        doc.close()
