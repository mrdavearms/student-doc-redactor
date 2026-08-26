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


def paste_body(mode='deidentify', **over):
    """Detect first, then select every match found. Returns the request body."""
    n = len(detect().json()['documents'][0]['matches'])
    body = {'mode': mode, 'student_name': 'Billy Bob',
            'selected_keys': [f'{PASTE_KEY}_{i}' for i in range(n)],
            'parent_names': ['Jane Bob'], 'family_names': [],
            'organisation_names': [], 'person_roles': {},
            'person_custom_labels': {}, 'ignored_people': []}
    body.update(over)
    return body


def people(**over):
    body = paste_body(**over)
    return client.post('/api/text/people', json=body), body


def test_people_endpoint_finds_the_parent_but_never_the_student():
    # PseudonymMap.people() (src/core/pseudonym_map.py) deliberately excludes
    # the student: their identity is already known, so there is nothing to
    # ask the user about. This mirrors
    # test_person_roles_api.py::test_the_student_is_never_offered_for_classification
    # so the paste wrapper is pinned to the same contract as the endpoint it wraps.
    r, _ = people()
    assert r.status_code == 200
    names = [p['full_name'] for p in r.json()['people']]
    assert 'Jane Bob' in names
    assert 'Billy Bob' not in names


def test_people_endpoint_offers_assignable_roles():
    r, _ = people()
    assert len(r.json()['roles']) > 0


def test_labels_endpoint_returns_every_person_except_the_student():
    _, body = people()
    r = client.post('/api/text/labels', json=body)
    assert r.status_code == 200
    labels = r.json()['labels']
    assert labels == {'Jane Bob': '[Parent]'}
    assert 'Billy Bob' not in labels


def test_folder_path_is_unused_by_the_people_endpoint():
    # The wrappers pass PASTE_KEY as folder_path. If build_map ever started
    # touching it, this would fail rather than writing to a bogus location.
    r, _ = people()
    assert r.status_code == 200
