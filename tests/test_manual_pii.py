import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import tempfile
from pathlib import Path

import fitz
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def _make_pdf(path, text):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=12)
    doc.save(str(path))
    doc.close()


def _detect(pdf_path, student_name="Nobody Relevant"):
    return client.post("/api/pii/detect", json={
        "pdf_paths": [str(pdf_path)],
        "student_name": student_name,
        "parent_names": [],
        "family_names": [],
        "organisation_names": [],
    })


def test_manual_item_is_appended_and_redacted_end_to_end():
    """A manually-added item the engines missed must actually get redacted
    when the user selects it and runs /api/redact — proving the cache-append
    approach flows through the existing redact endpoint unmodified."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        # "STUDENTREF12345" is not a name, email, or any pattern the regex
        # or NER engines recognise — detection must find zero matches.
        _make_pdf(pdf, "Internal reference code STUDENTREF12345 for this file.")

        det = _detect(pdf)
        assert det.status_code == 200, det.text
        assert det.json()["documents"][0]["matches"] == []

        manual = client.post("/api/pii/manual", json={
            "doc_path": str(pdf),
            "text": "STUDENTREF12345",
            "page_num": 1,
        })
        assert manual.status_code == 200, manual.text
        body = manual.json()
        assert body["index"] == 0
        assert body["match"]["text"] == "STUDENTREF12345"
        assert body["match"]["source"] == "manual"
        assert body["match"]["confidence_label"] == "high"

        red = client.post("/api/redact", json={
            "folder_path": tmp,
            "student_name": "Nobody Relevant",
            "parent_names": [],
            "family_names": [],
            "organisation_names": [],
            "redact_header_footer": False,
            "documents": [str(pdf)],
            "detected_pii": {},
            "selected_keys": [f"{pdf}_0"],
            "folder_action": "overwrite",
        })
        assert red.status_code == 200, red.text
        result = red.json()["document_results"][0]
        assert result["success"] is True
        assert result["items_redacted"] == 1

        out_doc = fitz.open(result["output_path"])
        out_text = out_doc[0].get_text()
        out_doc.close()
        assert "STUDENTREF12345" not in out_text


def test_manual_item_rejects_text_under_2_chars():
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Some content.")
        _detect(pdf)

        resp = client.post("/api/pii/manual", json={
            "doc_path": str(pdf), "text": "J", "page_num": 1,
        })
        assert resp.status_code == 400
        assert "at least 2 characters" in resp.json()["detail"]


def test_manual_item_rejects_out_of_range_page():
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Some content.")
        _detect(pdf)

        resp = client.post("/api/pii/manual", json={
            "doc_path": str(pdf), "text": "Missed Name", "page_num": 5,
        })
        assert resp.status_code == 400
        assert "does not exist in this document" in resp.json()["detail"]


def test_manual_item_requires_prior_detection():
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Some content.")
        # No _detect(pdf) call — no cache entry exists for this path.

        resp = client.post("/api/pii/manual", json={
            "doc_path": str(pdf), "text": "Missed Name", "page_num": 1,
        })
        assert resp.status_code == 400
        assert "Run detection first" in resp.json()["detail"]


# ── A lowercase everyday word added by hand (rule 7a) ─────────────────────
# Rule 7a declines all-lowercase hits for names that are also ordinary words,
# because a detector guess of "young" is usually the word. A teacher who TYPES
# "grace" in lowercase has said the lowercase form is the name, so that run
# matches it in any case. Before this, every stage declined it, the verifier
# agreed, and the run reported success with "grace" still readable.

def _redact_body(tmp, pdf, keys):
    return {
        "folder_path": tmp, "student_name": "Nobody Relevant",
        "parent_names": [], "family_names": [], "organisation_names": [],
        "redact_header_footer": False, "documents": [str(pdf)],
        "detected_pii": {}, "selected_keys": keys, "folder_action": "overwrite",
    }


def test_lowercase_common_word_added_by_hand_is_redacted():
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Message: hi grace, see you at lunch.")
        n = len(_detect(pdf).json()["documents"][0]["matches"])

        manual = client.post("/api/pii/manual", json={
            "doc_path": str(pdf), "text": "grace", "page_num": 1})
        assert manual.status_code == 200, manual.text
        # Not "matched only when capitalised": for this item that is untrue.
        assert manual.json()["match"]["common_word"] is False

        red = client.post("/api/redact", json=_redact_body(tmp, pdf, [f"{pdf}_{n}"]))
        assert red.status_code == 200, red.text
        result = red.json()["document_results"][0]
        assert result["success"] is True, result
        out = fitz.open(result["output_path"])
        text = out[0].get_text()
        out.close()
        assert "grace" not in text.lower()
        assert "see you at lunch." in text


def test_capitalised_common_word_added_by_hand_keeps_rule_7a():
    """Typed with a capital, the teacher means the name: lowercase uses of the
    word stay, exactly as for a detected name."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "report.pdf"
        _make_pdf(pdf, "Grace said grace before lunch.")
        n = len(_detect(pdf).json()["documents"][0]["matches"])

        manual = client.post("/api/pii/manual", json={
            "doc_path": str(pdf), "text": "Grace", "page_num": 1})
        assert manual.json()["match"]["common_word"] is True

        red = client.post("/api/redact", json=_redact_body(tmp, pdf, [f"{pdf}_{n}"]))
        result = red.json()["document_results"][0]
        out = fitz.open(result["output_path"])
        text = out[0].get_text()
        out.close()
        assert "Grace said" not in text
        assert "said grace before" in text


def test_lowercase_manual_word_in_pasted_text_is_removed():
    from backend.main import PASTE_KEY
    det = client.post("/api/text/detect", json={
        "text": "Notes: hi grace, see you at lunch.", "student_name": "Nobody Relevant",
        "parent_names": [], "family_names": [], "organisation_names": []})
    n = len(det.json()["documents"][0]["matches"])
    client.post("/api/pii/manual", json={"doc_path": PASTE_KEY, "text": "grace", "page_num": 1})

    for mode in ("redact", "deidentify"):
        r = client.post("/api/text/clean", json={
            "mode": mode, "student_name": "Nobody Relevant",
            "selected_keys": [f"{PASTE_KEY}_{n}"], "parent_names": [],
            "family_names": [], "organisation_names": [], "person_roles": {},
            "person_custom_labels": {}, "ignored_people": []})
        assert r.status_code == 200, r.text
        assert "grace" not in r.json()["text"].lower(), mode
        assert r.json()["leftovers"] == [], mode


def test_lowercase_exemption_ends_with_the_request():
    """The exemption is scoped to one run: afterwards rule 7a applies again."""
    from case_rules import NOT_LOWERCASE, any_case_for, case_mode
    with any_case_for(["grace"]):
        assert case_mode("grace") != NOT_LOWERCASE
        assert case_mode("Grace") != NOT_LOWERCASE
    assert case_mode("grace") == NOT_LOWERCASE
