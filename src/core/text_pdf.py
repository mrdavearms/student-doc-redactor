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

The block/sentinel mechanism only has to cope with characters WE choose. The
user's own pasted content goes through the same 'helv' font with no such
protection: a non-Latin-1 character in it (an emoji, a name in a non-Latin
script) silently renders as "?" too. There is no in-repo fix for that without
bundling a Unicode font (a new asset/dependency this project deliberately
avoids), so `render()` instead reports which of the user's own characters it
could not display, via `unsupported_characters()`, so the caller can warn
rather than silently ship corrupted content.

Most of what actually trips that failure is not exotic at all: Word and most
web editors auto-substitute curly quotes, em/en dashes, an ellipsis
character and a bullet character by default, so a completely ordinary pasted
sentence routinely contains several of these -- a warning alone would fire
on nearly every save while still handing back a PDF full of "?". So
TRANSLITERATIONS runs FIRST, silently swapping the common typographic
characters for their Latin-1 equivalents, and the unsupported-character scan
and the warning it produces are reserved for what genuinely cannot be
approximated this way -- non-Latin scripts and emoji.

ORDER MATTERS. choose_sentinel() must inspect the text AFTER transliteration
runs, not before: a substitution could otherwise introduce the very
character a stale, pre-transliteration sentinel choice had assumed absent,
and apply_redactions() would then black out that (legitimate) content when
it searches the page for the sentinel. That is the exact collision this
module exists to prevent (see choose_sentinel()'s docstring) -- reintroduced
one step earlier if the order here is ever "simplified".
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

# Typographic characters that Word/web pastes routinely introduce, which fall
# outside Latin-1 and would otherwise render as a literal "?" (each entry
# confirmed by direct rendering, not assumed -- see unsupported_characters()
# for why fitz.Font.has_glyph() alone can't be trusted for this). None of the
# replacement strings contain U+2588 (the block character) or any
# SENTINEL_CANDIDATES/FALLBACK_SENTINEL character, so transliterating can
# never manufacture a block run or collide with a sentinel by itself --
# choose_sentinel() still runs AFTER this substitution regardless, because
# that guarantee must hold for whatever this table contains, today or later.
TRANSLITERATIONS = {
    '‘': "'",    # left single quotation mark
    '’': "'",    # right single quotation mark
    '“': '"',    # left double quotation mark
    '”': '"',    # right double quotation mark
    '′': "'",    # prime
    '″': '"',    # double prime
    '–': '-',    # en dash
    # An em dash tight against its neighbouring words ("word—word") reads as
    # a hyphenated compound if simply swapped for "-"; " - " keeps the
    # visual pause the em dash conveys regardless of whether the source
    # already had spaces around it (in which case this doubles up a space --
    # a cosmetic wrinkle, not a correctness problem).
    '—': ' - ',
    '…': '...',  # horizontal ellipsis
    '•': '-',    # bullet -> plain-text list marker
    '™': '(TM)',  # trademark sign
    '€': 'EUR',   # euro sign -- no single Latin-1 character stands in
    # Non-breaking and other exotic spaces -> an ordinary breakable space.
    # (NBSP itself already renders fine -- it's normalised for consistency,
    # not because it corrupts to "?".) Zero-width space is the one exception:
    # it has no width, so replacing it with a visible space would add one
    # the user never typed -- it is dropped instead.
    ' ': ' ',    # no-break space
    ' ': ' ',    # en space
    ' ': ' ',    # em space
    ' ': ' ',    # figure space
    ' ': ' ',    # thin space
    ' ': ' ',    # hair space
    ' ': ' ',    # narrow no-break space
    '​': '',     # zero-width space
}


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

    if best is not None:
        return text[:best], text[best:]

    # No whitespace break fits on the page -- typically one giant unbroken
    # token (a URL, an ID string, prose pasted with no spaces). A naive
    # len(text) // 2 split point was never verified to actually render,
    # and PyMuPDF cannot wrap a single word: it either fits or it doesn't.
    # An unverified split silently dropped the ENTIRE chunk (leftover < 0,
    # zero characters rendered) -- so binary-search on raw character count
    # for the largest prefix that is confirmed, via _fits(), to render.
    lo, hi, best_n = 1, len(text), 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if _fits(text[:mid], rect):
            best_n = mid
            lo = mid + 1
        else:
            hi = mid - 1

    # best_n starts at 1 and is only ever raised, so at least one character
    # is always split off -- guaranteed forward progress even in the
    # pathological case where a single character doesn't fit the rect
    # (which would otherwise spin the caller's pagination loop forever on
    # empty chunks).
    return text[:best_n], text[best_n:]


def _transliterate(text: str) -> str:
    """Swap common typographic characters for their Latin-1 equivalents --
    see TRANSLITERATIONS for the table and why each entry is there."""
    for src, dst in TRANSLITERATIONS.items():
        text = text.replace(src, dst)
    return text


def unsupported_characters(text: str) -> list:
    """
    Distinct characters in `text` (first-seen order) that render()'s font
    cannot display -- these come out as a literal "?" in the saved PDF.

    fitz.Font(FONT_NAME).has_glyph() alone is NOT a reliable predictor here:
    it reports whether the underlying substitute font FILE contains a glyph
    for a codepoint, but a base-14 font referenced by name (like 'helv') is
    written into the PDF as a "simple" font, addressed through a single-byte
    Latin-1 table -- so has_glyph() answers "yes" for characters the file
    happens to contain but insert_textbox() can never actually reach, e.g.
    '€', an em dash, or curly quotes (all confirmed by direct rendering to
    produce '?', despite has_glyph() reporting a glyph exists). A character
    only survives both constraints: its codepoint must fit in one byte
    (<= 0xFF) AND the font must have a glyph for it -- the latter half
    catches the few Latin-1-range codepoints (the C0/C1 control characters)
    that have no glyph at all. Whitespace is exempt: it lays out lines and
    is never rendered as a glyph, so has_glyph() correctly says "no" for it
    while it renders perfectly fine.

    Verified directly against fitz.Font('helv') + a real insert_textbox()
    render across the full Latin-1 range, common CJK/Hebrew/Arabic/emoji,
    and the specific "looks covered but isn't" cases above -- this rule
    matched actual rendered output with zero mismatches.
    """
    font = fitz.Font(FONT_NAME)
    seen = set()
    unsupported = []
    for char in text:
        if char in seen or char.isspace():
            continue
        seen.add(char)
        if ord(char) > 0xFF or not font.has_glyph(ord(char)):
            unsupported.append(char)
    return unsupported


def _strip_metadata(doc: fitz.Document) -> None:
    doc.set_metadata({
        'author': '', 'title': '', 'subject': '', 'creator': '',
        'producer': '', 'keywords': '', 'creationDate': '', 'modDate': '',
    })
    doc.del_xml_metadata()


def render(text: str, out_path, block: str) -> list:
    """
    Lay `text` out as a PDF, turning each `block` run into a black box.

    Returns the distinct characters (first-seen order) of the user's OWN
    content that this renderer's font cannot display and which therefore
    show up as "?" in the saved PDF -- empty if none. Common typographic
    characters (curly quotes, em/en dashes, an ellipsis, ...) are silently
    transliterated to Latin-1 equivalents before that check runs, so the
    warning is reserved for what genuinely can't be approximated -- non-
    Latin scripts and emoji -- see TRANSLITERATIONS. Checked with the
    `block` runs removed, since those are never actually inserted into the
    page (they become the sentinel, then get redacted away) and so can
    never appear as "?" no matter what character they use. The save still
    succeeds either way; the caller decides what to do with the list.

    ORDER IS DELIBERATE: transliteration runs before choose_sentinel(),
    never after. choose_sentinel()'s whole contract is "absent from the
    exact text about to be laid out and later searched for" -- picking it
    from the pre-transliteration text would let a substitution reintroduce
    a character the choice had assumed absent, and search_for() would then
    black out that legitimate, newly-introduced content along with the real
    block runs. Do not reorder this.
    """
    text = _transliterate(text or '')

    sentinel = choose_sentinel(text)
    laid_out = text.replace(block, sentinel)

    unsupported = unsupported_characters(text.replace(block, ''))

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

    return unsupported
