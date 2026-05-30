import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import tempfile
from pathlib import Path
from unittest.mock import patch

import fitz
from text_extractor import TextExtractor


def _make_pdf(path, text="Hello world"):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=12)
    doc.save(str(path))
    doc.close()


def test_coords_returns_empty_and_does_not_raise_on_bad_page():
    """An out-of-range page must return [] and must not raise."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.pdf"
        _make_pdf(src)
        extractor = TextExtractor()
        result = extractor.get_text_with_coordinates(src, page_num=99)
        assert result == []


def test_coords_closes_document_even_on_error():
    """The opened fitz document must be closed even when page access raises."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.pdf"
        _make_pdf(src)
        extractor = TextExtractor()
        opened = []
        real_open = fitz.open

        def tracking_open(*a, **k):
            d = real_open(*a, **k)
            opened.append(d)
            return d

        # page_num=99 is out of range → indexing raises inside the try block.
        with patch("text_extractor.fitz.open", tracking_open):
            extractor.get_text_with_coordinates(src, page_num=99)

        assert opened, "a document should have been opened"
        assert opened[0].is_closed, "document must be closed on the error path"


def test_coords_happy_path_returns_spans():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.pdf"
        _make_pdf(src, "Findable text here")
        extractor = TextExtractor()
        result = extractor.get_text_with_coordinates(src, page_num=1)
        assert any("Findable" in text for text, _bbox in result)


def test_preview_endpoint_closes_doc_and_validates_range():
    """The /api/preview endpoint must close its document on both the happy
    path and the out-of-range path, and still return the documented results."""
    from fastapi.testclient import TestClient
    from backend.main import app

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "doc.pdf"
        _make_pdf(src, "Preview me")

        opened = []
        real_open = fitz.open

        def tracking_open(*a, **k):
            d = real_open(*a, **k)
            opened.append(d)
            return d

        client = TestClient(app)
        # preview_page does a function-scoped `import fitz`, so it resolves
        # `fitz.open` off the fitz module object itself — patch it there.
        with patch.object(fitz, "open", tracking_open):
            ok = client.post("/api/preview", json={"pdf_path": str(src), "page_num": 0})
            bad = client.post("/api/preview", json={"pdf_path": str(src), "page_num": 99})

        assert ok.status_code == 200
        assert ok.json()["total_pages"] == 1
        assert bad.status_code == 400
        assert opened, "preview should have opened documents"
        assert all(d.is_closed for d in opened), "every opened doc must be closed"
