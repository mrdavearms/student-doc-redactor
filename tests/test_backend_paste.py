import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

from fastapi.testclient import TestClient
from backend.main import app, PASTE_KEY, PASTE_MAX_CHARS

client = TestClient(app)

SAMPLE = ('Billy Bob was absent on 12/03/2026. His mother Jane Bob was '
          'contacted on 0412 345 678.')


def detect(text=SAMPLE, **over):
    body = {'text': text, 'student_name': 'Billy Bob',
            'parent_names': ['Jane Bob'], 'family_names': [],
            'organisation_names': []}
    body.update(over)
    return client.post('/api/text/detect', json=body)


def test_detect_returns_one_pseudo_document_under_the_reserved_key():
    r = detect()
    assert r.status_code == 200
    docs = r.json()['documents']
    assert len(docs) == 1
    assert docs[0]['path'] == PASTE_KEY
    assert r.json()['total_matches'] > 0


def test_ocr_pages_is_empty_so_the_fuzzy_verifier_never_arms():
    # CLAUDE.md rule 45's fuzzy pass is for OCR. On typed text it would flag a
    # classmate "Smyth" against student "Smith" and falsely quarantine.
    assert detect().json()['documents'][0]['ocr_pages'] == []


def test_empty_text_is_rejected():
    assert detect(text='   ').status_code == 400


def test_oversize_text_is_rejected_with_a_redirect_message():
    r = detect(text='a ' * PASTE_MAX_CHARS)
    assert r.status_code == 400
    assert 'document' in r.json()['detail'].lower()


def test_pii_detect_refuses_the_reserved_key():
    r = client.post('/api/pii/detect', json={
        'pdf_paths': [PASTE_KEY], 'student_name': 'Billy Bob',
        'parent_names': [], 'family_names': [], 'organisation_names': []})
    assert r.status_code == 400
