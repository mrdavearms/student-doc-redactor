"""
Concurrency regression tests for the shared detection cache in backend/main.py.

Both /api/pii/detect (documents) and /api/text/detect (pasted text) are
synchronous `def` handlers, so Starlette runs each on a threadpool -- and a
client disconnect (the user pressing Back mid-scan) does NOT cancel the
in-flight work. Two scans can genuinely overlap in the real app: the user
starts a slow scan, presses Back, edits, and starts a second scan that
finishes first. Before the generation-counter fix, whichever detection
finished LAST always overwrote the cache, regardless of which one the user
was actually reviewing -- so "Clean"/"Redact" could act on text or documents
the user never approved. See CLAUDE.md and the concurrency-fix report for the
full writeup.

These tests avoid real thread timing entirely. A sleep/timing-based test
would be flaky and would prove nothing on a fast machine. Instead they use
the fact that TestClient requests run synchronously on the calling thread:
by monkeypatching the slow detection call (DetectionService.detect_in_text /
detect_all), a "newer" request is driven to full completion -- including its
own publish -- from INSIDE the "older" request's still-running detection
work, before the older request gets a chance to publish. This pins the
ordering exactly, on every run, on any machine.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from backend import main
from backend.main import app, PASTE_KEY, _detection_cache
from src.services.detection_service import DetectionService

client = TestClient(app)

OLD_TEXT = "Old scan: Billy Bob was seen by Dr Smith on 1 March."
NEW_TEXT = "New scan: Jane Doe met with Mrs Adams on 2 March."


def _paste_body(text, student_name):
    return {
        'text': text, 'student_name': student_name,
        'parent_names': [], 'family_names': [], 'organisation_names': [],
    }


def _make_pdf(path, text):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=12)
    doc.save(str(path))
    doc.close()


def _race_two_pastes(monkeypatch):
    """
    Drive an OLD /api/text/detect (OLD_TEXT) whose detection work, while
    "running", nests a NEW /api/text/detect (NEW_TEXT) through to full
    completion and publish -- then lets OLD finish and try to publish too.

    Returns OLD's response. NEW's response is asserted 200 inside the mock,
    since nothing outside this function ever sees it directly.
    """
    real_detect_in_text = DetectionService.detect_in_text
    state = {'nested': False}

    def fake_detect_in_text(self, text):
        if text == OLD_TEXT and not state['nested']:
            state['nested'] = True
            resp = client.post('/api/text/detect', json=_paste_body(NEW_TEXT, 'Jane Doe'))
            assert resp.status_code == 200, resp.text
        return real_detect_in_text(self, text)

    monkeypatch.setattr(DetectionService, 'detect_in_text', fake_detect_in_text)

    return client.post('/api/text/detect', json=_paste_body(OLD_TEXT, 'Billy Bob'))


def test_older_paste_detection_completing_after_a_newer_one_does_not_win(monkeypatch):
    old_resp = _race_two_pastes(monkeypatch)

    assert old_resp.status_code == 409
    assert 'newer' in old_resp.json()['detail'].lower()

    # The cache must hold the NEWER run's text, even though the OLDER
    # request's detection work is the one that finished last in wall time.
    cached_text = _detection_cache[PASTE_KEY]['text_data']['pages'][1]['text']
    assert cached_text == NEW_TEXT


def test_loser_gets_409_and_winner_stays_cleanable(monkeypatch):
    _race_two_pastes(monkeypatch)

    n = len(_detection_cache[PASTE_KEY]['matches'])
    assert n > 0
    clean_resp = client.post('/api/text/clean', json={
        'mode': 'redact', 'student_name': 'Jane Doe',
        'selected_keys': [f'{PASTE_KEY}_{i}' for i in range(n)],
        'parent_names': [], 'family_names': [], 'organisation_names': [],
        'person_roles': {}, 'person_custom_labels': {}, 'ignored_people': [],
    })
    assert clean_resp.status_code == 200
    cleaned = clean_resp.json()['text']
    # We cleaned the NEWER run's text, not the text the losing (older)
    # request scanned.
    assert 'Jane Doe' not in cleaned
    assert 'New scan' in cleaned
    assert 'Old scan' not in cleaned
    assert 'Billy Bob' not in cleaned


def test_document_and_paste_detection_race_newest_started_wins(monkeypatch, tmp_path):
    """Cross-pathway: a document scan (/api/pii/detect) and a paste scan
    (/api/text/detect) share the same cache and can overlap the same way.
    Whichever STARTED later must win, regardless of which endpoint it is."""
    pdf = tmp_path / "report.pdf"
    _make_pdf(pdf, "Old document scan: Joe Bloggs attended with Mary Bloggs.")

    real_detect_all = DetectionService.detect_all
    state = {'nested': False}

    def fake_detect_all(self, pdf_paths):
        if not state['nested']:
            state['nested'] = True
            resp = client.post('/api/text/detect', json=_paste_body(NEW_TEXT, 'Jane Doe'))
            assert resp.status_code == 200, resp.text
        return real_detect_all(self, pdf_paths)

    monkeypatch.setattr(DetectionService, 'detect_all', fake_detect_all)

    old_resp = client.post('/api/pii/detect', json={
        'pdf_paths': [str(pdf)], 'student_name': 'Joe Bloggs',
        'parent_names': ['Mary Bloggs'], 'family_names': [], 'organisation_names': [],
    })

    assert old_resp.status_code == 409
    # The document scan lost the race; the cache holds only the paste run's
    # entry -- not a mix of both, and not the document's.
    assert str(pdf) not in _detection_cache
    assert PASTE_KEY in _detection_cache
    assert _detection_cache[PASTE_KEY]['text_data']['pages'][1]['text'] == NEW_TEXT


def test_an_ordinary_single_paste_detection_still_publishes_and_cleans():
    """No-regression check: outside of any race, a single detect -> clean
    round trip must behave exactly as it did before the generation counter."""
    text = "Plain run: Billy Bob attended with parent Jane Bob."
    r = client.post('/api/text/detect', json=_paste_body(text, 'Billy Bob'))
    assert r.status_code == 200
    n = len(r.json()['documents'][0]['matches'])
    assert n > 0

    clean_resp = client.post('/api/text/clean', json={
        'mode': 'redact', 'student_name': 'Billy Bob',
        'selected_keys': [f'{PASTE_KEY}_{i}' for i in range(n)],
        'parent_names': [], 'family_names': [], 'organisation_names': [],
        'person_roles': {}, 'person_custom_labels': {}, 'ignored_people': [],
    })
    assert clean_resp.status_code == 200
    assert 'Billy Bob' not in clean_resp.json()['text']


def test_an_ordinary_single_document_detection_still_publishes_and_redacts(tmp_path):
    """No-regression check for the document pathway."""
    pdf = tmp_path / "plain.pdf"
    _make_pdf(pdf, "Student Joe Bloggs attended with parent Mary Bloggs.")

    det = client.post('/api/pii/detect', json={
        'pdf_paths': [str(pdf)], 'student_name': 'Joe Bloggs',
        'parent_names': ['Mary Bloggs'], 'family_names': [], 'organisation_names': [],
    })
    assert det.status_code == 200
    matches = det.json()['documents'][0]['matches']
    assert len(matches) >= 1

    red = client.post('/api/redact', json={
        'folder_path': str(tmp_path), 'student_name': 'Joe Bloggs',
        'parent_names': ['Mary Bloggs'], 'family_names': [], 'organisation_names': [],
        'redact_header_footer': False, 'documents': [str(pdf)],
        'detected_pii': {}, 'selected_keys': [f'{pdf}_0'],
        'folder_action': 'overwrite',
    })
    assert red.status_code == 200
    assert red.json()['document_results'][0]['items_redacted'] == 1


def test_discard_supersedes_a_scan_the_user_abandoned(monkeypatch):
    """
    /api/text/discard must also claim a generation.

    The renderer aborts a scan by dropping the response, but the endpoint is
    synchronous and keeps running. Without this, a scan abandoned just before
    the user left the flow would publish the very slab they asked to discard
    back into the cache -- leaving their pasted text resident in backend
    memory with nothing on screen to explain why.
    """
    published = {}

    def slow_detect(self, text):
        # The user leaves the flow while this scan is still running.
        assert client.post('/api/text/discard').status_code == 200
        published['discarded_midway'] = True
        return []

    monkeypatch.setattr(DetectionService, 'detect_in_text', slow_detect)
    resp = client.post('/api/text/detect',
                       json=_paste_body('Billy Bob was absent.', 'Billy Bob'))

    assert published['discarded_midway']
    # The abandoned scan is superseded, so it cannot re-seed the cache.
    assert resp.status_code == 409
    assert PASTE_KEY not in _detection_cache


# ── Discarding a finished run ────────────────────────────────────────────

class TestDiscardDetection:
    """
    The document pathway's equivalent of /api/text/discard. Called by the
    store's reset(), so a finished run does not sit in memory until the next
    one replaces it.
    """

    def test_discard_empties_the_cache(self):
        main._detection_cache.clear()
        main._detection_cache["/tmp/a.pdf"] = {"matches": [], "text_data": {}}
        main._detection_cache["/tmp/b.pdf"] = {"matches": [], "text_data": {}}

        r = client.post("/api/detection/discard")

        assert r.status_code == 200
        assert r.json()["discarded"] == 2
        assert main._detection_cache == {}

    def test_discard_also_clears_pasted_text(self):
        main._detection_cache.clear()
        main._detection_cache[main.PASTE_KEY] = {"matches": [], "text_data": {}}

        client.post("/api/detection/discard")

        assert main.PASTE_KEY not in main._detection_cache

    def test_discard_on_an_empty_cache_is_a_no_op(self):
        main._detection_cache.clear()

        r = client.post("/api/detection/discard")

        assert r.status_code == 200
        assert r.json()["discarded"] == 0

    def test_an_abandoned_scan_cannot_republish_after_a_discard(self):
        """
        Detection is synchronous, so a scan the renderer walked away from keeps
        running. Without claiming a generation the discard would be undone by
        whatever finishes next — the same trap /api/text/discard closes.
        """
        main._detection_cache.clear()
        stale_generation = main._begin_detection()

        client.post("/api/detection/discard")
        republished = main._publish_detection(
            stale_generation, {"/tmp/a.pdf": {"matches": [], "text_data": {}}}
        )

        assert republished is False
        assert main._detection_cache == {}
