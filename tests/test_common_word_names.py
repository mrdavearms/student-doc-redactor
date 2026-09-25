"""
Names that are also ordinary English words ("Will", "Young", "Grace", "Long")
match only when they are not written entirely in lowercase (rule 7a).

A student called William Young used to have every "young" in the report
offered, and because a selected string is redacted on every page (rule 11a),
unticking those rows changed nothing.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

from case_rules import NOT_LOWERCASE, case_mode
from common_words import COMMON_WORDS
from pii_orchestrator import PIIOrchestrator


def _texts(matches):
    return sorted(m.text for m in matches)


class TestShippedWordList:

    def test_the_names_this_work_is_for_are_on_it(self):
        for name in ['Will', 'Young', 'Grace', 'Long', 'Bill', 'Pat', 'Sue', 'Ted', 'Ray', 'Art']:
            assert case_mode(name) == NOT_LOWERCASE, name

    def test_only_plain_lowercase_words(self):
        assert len(COMMON_WORDS) > 10000
        assert all(w.isalpha() and w.islower() and len(w) >= 3 for w in COMMON_WORDS)

    def test_which_common_australian_names_are_caught(self):
        """
        A fixed sample of common Australian given names and surnames. Being on
        the list means "matched only when not all lowercase" — harmless for a
        name, which prose never writes in lowercase. This test pins the set so
        a change to the list that catches a new name fails HERE, where someone
        reads it, rather than surprising a teacher.
        """
        sample = """Smith Jones Williams Brown Wilson Taylor Johnson White Martin
        Anderson Thompson Nguyen Thomas Walker Harris Lee Ryan Robinson Kelly King
        Davis Wright Evans Roberts Green Hall Wood Jackson Clarke Patel Khan Lewis
        James Phillips Mitchell Turner Young Cook Hill Scott Long Singh Chen Wang
        Tran Pham Kim Park Baker Campbell Stewart Murphy Edwards Morris Moore Clark
        Bell Parker Cooper Hughes Price Ward Hunter Carter Mason Fisher Graham Page
        Stone Knight Oliver Noah Jack William Leo Lucas Henry Charlie Charlotte
        Amelia Isla Olivia Mia Ava Grace Willow Harper Chloe Ruby Sophie Ella Zoe
        Lily Ivy Archie Max Hope Will Summer Autumn Jade Rose Violet Daisy Poppy
        Hazel Pearl Joy Faith Mark Grant Bill Pat Sue Ray Art Ted Bob Rob Penny
        May June Frank Victoria Christian Patience Harmony""".split()
        caught = sorted(n for n in sample if case_mode(n) == NOT_LOWERCASE)
        assert caught == sorted("""Art Autumn Baker Bell Bill Bob Brown Christian
        Cook Daisy Faith Frank Grace Grant Green Hall Harmony Hazel Hill Hope
        Hunter Ivy Jack Jade Joy June King Knight Lee Long Mark Mason Max May
        Pat Page Park Patience Pearl Penny Poppy Price Ray Rob Rose Ruby Smith
        Stone Sue Summer Ted Violet Walker Ward White Will Wood Young""".split())


class TestDetection:

    def test_lowercase_word_is_not_offered(self):
        orch = PIIOrchestrator("William Young", parent_names=["Grace Long"])
        found = _texts(orch.detect_pii_in_text(
            "Young people will need long breaks and a grace period.", 1))
        assert 'young' not in found
        assert 'long' not in found and 'grace' not in found

    def test_capitalised_and_capitals_are_offered(self):
        orch = PIIOrchestrator("William Young", parent_names=["Grace Long"])
        found = _texts(orch.detect_pii_in_text("Mr Young spoke to Mrs Long.", 1))
        assert 'Young' in found and 'Long' in found
        found = _texts(orch.detect_pii_in_text("STUDENT: YOUNG", 1))
        assert 'YOUNG' in found

    def test_name_row_survives_a_lowercase_word_on_the_same_line(self):
        """Deduplication keys on lowercase text; the lowercase hit must be
        dropped before it can displace the name."""
        orch = PIIOrchestrator("William Young")
        matches = orch.detect_pii_in_text("Mr Young said young people thrive.", 1)
        assert [m.text for m in matches if m.text.lower() == 'young'] == ['Young']

    def test_sentence_initial_word_is_still_offered(self):
        """The accepted trade-off, as rule 7 accepted it for "Do" and "He"."""
        orch = PIIOrchestrator("William Young")
        found = _texts(orch.detect_pii_in_text("Young people often need breaks.", 1))
        assert 'Young' in found

    def test_full_name_is_unaffected(self):
        orch = PIIOrchestrator("William Young")
        found = _texts(orch.detect_pii_in_text("william young was absent", 1))
        assert 'william young' in found

    def test_uncommon_name_still_matches_in_lowercase(self):
        orch = PIIOrchestrator("Minh Nguyen")
        found = _texts(orch.detect_pii_in_text("contact nguyen family", 1))
        assert 'nguyen' in found


# ---------------------------------------------------------------------------
# End to end: the check that protects the whole design (plan step 5)
# ---------------------------------------------------------------------------
#
# Every stage must agree that "young" is not the surname Young. If detection,
# the redactor, the OCR redactor, a verifier or de-identification disagreed,
# a correctly processed document would report a name "still visible" and
# quarantine itself. Every row is ticked, as "Accept all" does.

import io
from pathlib import Path

import fitz
import pytest
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

STUDENT = "William Young"
PARENTS = ["Grace Long"]

REPORT = [
    "STUDENT: WILLIAM YOUNG      PARENT: GRACE LONG",
    "LONG-TERM GOALS",
    "William Young is a young learner who will need long breaks.",
    "Mrs Long gave us a grace period; Mr Young agreed.",
    "Young people often find long tasks hard. Grace will call.",
    "William's long-term aim is to read with younger students.",
]
SCAN = [
    "Paediatric review for William Young",
    "His mother Grace Long attended",
    "He is a young boy with a long history",
]
SCREENSHOT = [
    "From: Grace Long",
    "William will be late, a long appointment",
]
WORDS = ["young", "long", "grace", "will"]


def _tesseract_available():
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _png(lines, width, size, pad):
    font = ImageFont.load_default(size=size)
    step = int(size * 1.7)
    img = Image.new("RGB", (width, pad * 2 + step * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((pad, pad + i * step), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _write(page, lines):
    y = 72
    for line in lines:
        page.insert_text((60, y), line, fontsize=11)
        y += 20
    return y


def _corpus(folder):
    """A text-layer report, the same with a scanned page, and the same with
    a pasted email screenshot."""
    paths = []
    for name in ("report", "scanned", "screenshot"):
        doc = fitz.open()
        page = doc.new_page()
        y = _write(page, REPORT)
        if name == "screenshot":
            page.insert_image(fitz.Rect(60, y + 10, 460, y + 110),
                              stream=_png(SCREENSHOT, 1200, 44, 30))
        if name == "scanned":
            scan = doc.new_page()
            scan.insert_image(fitz.Rect(0, 0, scan.rect.width, scan.rect.width * 0.4),
                              stream=_png(SCAN, 1700, 52, 120))
        path = folder / f"{name}.pdf"
        doc.save(str(path))
        doc.close()
        paths.append(path)
    return paths


def _lowercase_counts(text):
    import re
    return {w: len(re.findall(r"(?<![A-Za-z])" + w + r"(?![A-Za-z])", text)) for w in WORDS}


@pytest.fixture(scope="module")
def detected(tmp_path_factory):
    from src.services.detection_service import DetectionService
    folder = tmp_path_factory.mktemp("common_words")
    docs = _corpus(folder)
    results = DetectionService(STUDENT, parent_names=PARENTS).detect_all(docs)
    assert results.failed_documents == []
    detected_pii, selections = {}, {}
    for doc in results.documents:
        pii = results.pii_by_document[doc]
        detected_pii[doc] = {"matches": pii.matches, "text_data": pii.text_data}
        for i in range(len(pii.matches)):
            selections[f"{doc}_{i}"] = True
    return folder, results.documents, detected_pii, selections


@pytest.mark.skipif(not _tesseract_available(), reason="Tesseract not installed")
class TestNoQuarantineEitherPathway:

    def test_detection_offers_no_lowercase_word(self, detected):
        _, docs, detected_pii, _ = detected
        for doc in docs:
            texts = [m.text for m in detected_pii[doc]["matches"]]
            assert not [t for t in texts if t.lower() in WORDS and t.islower()], doc.name

    def test_redact_pathway(self, detected):
        from src.services.redaction_service import RedactionRequest, RedactionService
        folder, docs, detected_pii, selections = detected
        results = RedactionService().execute(RedactionRequest(
            folder_path=folder, student_name=STUDENT, documents=list(docs),
            detected_pii=detected_pii, user_selections=selections,
            parent_names=PARENTS, custom_output_path=folder / "redacted"))

        for r in results.document_results:
            assert r.success, (r.document_name, r.verification_failures, r.error_message)
            assert r.verification_failures == []
            with fitz.open(str(r.output_path)) as doc:
                text = doc[0].get_text()
            # Every lowercase word on the text layer survives...
            assert _lowercase_counts(text) == _lowercase_counts("\n".join(REPORT)), r.document_name
            # ...and no written form of the names does.
            for name in ("William", "Young", "YOUNG", "Grace", "GRACE", "Long", "LONG"):
                assert name not in text, (r.document_name, name)

    def test_deidentify_pathway(self, detected):
        from src.services.deidentification_service import (
            DeidentificationService, DeidentifyRequest,
        )
        folder, docs, detected_pii, selections = detected
        results = DeidentificationService().execute(DeidentifyRequest(
            folder_path=folder, student_name=STUDENT, documents=list(docs),
            detected_pii=detected_pii, user_selections=selections,
            parent_names=PARENTS, custom_output_path=folder / "deidentified"))

        for r in results.document_results:
            assert r.success, (r.document_name, r.verification_failures, r.error_message)
            assert r.verification_failures == []
            text = Path(r.output_path).read_text()
            counts = _lowercase_counts(text)
            expected = _lowercase_counts("\n".join(REPORT))
            # The scanned page adds its own lowercase words to the output.
            assert all(counts[w] >= expected[w] for w in WORDS), (r.document_name, counts)
            for name in ("William", "Young", "YOUNG", "Grace", "GRACE", "Long", "LONG"):
                assert name not in text, (r.document_name, name)


class TestPastePathway:
    """Pasted text: detection, then both cleaning modes, through the API."""

    TEXT = "\n".join(REPORT)

    @pytest.mark.parametrize("mode", ["redact", "deidentify"])
    def test_clean_keeps_the_words_and_reports_no_leftovers(self, mode):
        from fastapi.testclient import TestClient
        from backend.main import PASTE_KEY, app
        client = TestClient(app)
        people = {"student_name": STUDENT, "parent_names": PARENTS,
                  "family_names": [], "organisation_names": []}
        r = client.post("/api/text/detect", json={"text": self.TEXT, **people})
        assert r.status_code == 200
        matches = r.json()["documents"][0]["matches"]
        assert not [m["text"] for m in matches if m["text"].lower() in WORDS and m["text"].islower()]

        r = client.post("/api/text/clean", json={
            "mode": mode, **people,
            "selected_keys": [f"{PASTE_KEY}_{i}" for i in range(len(matches))],
            "person_roles": {}, "person_custom_labels": {}, "ignored_people": []})
        assert r.status_code == 200
        body = r.json()
        assert body["leftovers"] == []
        assert _lowercase_counts(body["text"]) == _lowercase_counts(self.TEXT)
        for name in ("William", "Young", "YOUNG", "Grace", "GRACE", "Long", "LONG"):
            assert name not in body["text"], name


@pytest.mark.skipif(not _tesseract_available(), reason="Tesseract not installed")
class TestScannedPageLowercaseMisread:
    """Plan step 7, option one: the accepted leak, and the warning that says so.

    A poor scan can read the surname Young as "young". The OCR redactor leaves
    that word alone and the OCR verifier agrees, so the run succeeds with the
    word readable. The scanned-page warning must then carry SCANNED_PAGE_NOTE.
    The scan here literally shows "young", standing in for the misread.
    """

    @pytest.fixture(scope="class")
    def misread(self, tmp_path_factory):
        from src.services.detection_service import DetectionService
        folder = tmp_path_factory.mktemp("misread")
        doc = fitz.open()
        _write(doc.new_page(), ["Report for William Young.", "Mr Young attended."])
        scan = doc.new_page()
        scan.insert_image(fitz.Rect(0, 0, scan.rect.width, scan.rect.width * 0.3),
                          stream=_png(["Seen today with mr young present"], 1700, 52, 120))
        path = folder / "misread.pdf"
        doc.save(str(path))
        doc.close()
        results = DetectionService(STUDENT, parent_names=PARENTS).detect_all([path])
        pii = results.pii_by_document[path]
        assert 2 in pii.text_data["ocr_pages"]
        detected_pii = {path: {"matches": pii.matches, "text_data": pii.text_data}}
        selections = {f"{path}_{i}": True for i in range(len(pii.matches))}
        return folder, path, detected_pii, selections

    def test_redact_succeeds_and_warns(self, misread):
        from case_rules import SCANNED_PAGE_NOTE
        from src.services.redaction_service import RedactionRequest, RedactionService
        folder, path, detected_pii, selections = misread
        result = RedactionService().execute(RedactionRequest(
            folder_path=folder, student_name=STUDENT, documents=[path],
            detected_pii=detected_pii, user_selections=selections,
            parent_names=PARENTS, custom_output_path=folder / "redacted",
        )).document_results[0]
        assert result.success, result.verification_failures
        assert any(SCANNED_PAGE_NOTE in w for w in result.ocr_warnings), result.ocr_warnings

    def test_deidentify_succeeds_and_warns(self, misread):
        from case_rules import SCANNED_PAGE_NOTE
        from src.services.deidentification_service import (
            DeidentificationService, DeidentifyRequest,
        )
        folder, path, detected_pii, selections = misread
        result = DeidentificationService().execute(DeidentifyRequest(
            folder_path=folder, student_name=STUDENT, documents=[path],
            detected_pii=detected_pii, user_selections=selections,
            parent_names=PARENTS, custom_output_path=folder / "deidentified",
        )).document_results[0]
        assert result.success, result.verification_failures
        text = Path(result.output_path).read_text()
        assert "young" in text  # the leak this option accepts
        assert any(SCANNED_PAGE_NOTE in w for w in result.ocr_warnings), result.ocr_warnings

    def test_no_note_without_a_common_word_name(self, tmp_path):
        from case_rules import SCANNED_PAGE_NOTE
        from src.services.detection_service import DetectionService
        from src.services.redaction_service import RedactionRequest, RedactionService
        doc = fitz.open()
        _write(doc.new_page(), ["Report for Minh Nguyen."])
        scan = doc.new_page()
        scan.insert_image(fitz.Rect(0, 0, scan.rect.width, scan.rect.width * 0.3),
                          stream=_png(["Seen today with Minh Nguyen"], 1700, 52, 120))
        path = tmp_path / "plain.pdf"
        doc.save(str(path))
        doc.close()
        pii = DetectionService("Minh Nguyen").detect_all([path]).pii_by_document[path]
        result = RedactionService().execute(RedactionRequest(
            folder_path=tmp_path, student_name="Minh Nguyen", documents=[path],
            detected_pii={path: {"matches": pii.matches, "text_data": pii.text_data}},
            user_selections={f"{path}_{i}": True for i in range(len(pii.matches))},
            custom_output_path=tmp_path / "redacted",
        )).document_results[0]
        assert result.success
        assert result.ocr_warnings
        assert not any(SCANNED_PAGE_NOTE in w for w in result.ocr_warnings)


class TestReviewBadgeFlag:
    """The review screen's "common word" badge reads common_word from every
    endpoint that returns matches (plan step 8)."""

    PEOPLE = {"student_name": STUDENT, "parent_names": PARENTS,
              "family_names": [], "organisation_names": []}

    @staticmethod
    def _client():
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    def test_document_detection(self, tmp_path):
        doc = fitz.open()
        _write(doc.new_page(), ["Mr Young and Minh Nguyen met William Young."])
        path = tmp_path / "flag.pdf"
        doc.save(str(path))
        doc.close()
        r = self._client().post("/api/pii/detect", json={"pdf_paths": [str(path)], **self.PEOPLE})
        assert r.status_code == 200
        flags = {m["text"]: m["common_word"] for m in r.json()["documents"][0]["matches"]}
        assert flags["Young"] is True
        assert flags["William Young"] is False

    def test_pasted_text_and_a_manual_item(self):
        from backend.main import PASTE_KEY
        client = self._client()
        r = client.post("/api/text/detect", json={"text": "Mr Young met Grace Long.", **self.PEOPLE})
        assert r.status_code == 200
        flags = {m["text"]: m["common_word"] for m in r.json()["documents"][0]["matches"]}
        assert flags["Young"] is True and flags["Grace Long"] is False

        add = client.post("/api/pii/manual", json={
            "doc_path": PASTE_KEY, "text": "Grace", "page_num": 1, "category": "Manual"})
        assert add.status_code == 200
        assert add.json()["match"]["common_word"] is True
