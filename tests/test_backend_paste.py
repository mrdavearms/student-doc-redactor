import sys, os
import json
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import fitz
from fastapi.testclient import TestClient
from backend.main import app, PASTE_KEY, PASTE_MAX_CHARS, _detection_cache

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


def test_lone_utf16_surrogate_is_rejected_cleanly():
    # Valid JSON (JS strings permit unpaired surrogates) but not valid
    # Unicode — reachable from corrupted clipboard data. Previously reached
    # spaCy/Presidio's NER analysis and 500'd with an internal exception
    # string ("'utf-8' codec can't encode character '\ud800'...").
    #
    # httpx's own json= helper uses ensure_ascii=False and would raise
    # UnicodeEncodeError itself trying to build the request — a real client
    # (JS's JSON.stringify + fetch) always escapes a lone surrogate to plain
    # ASCII \ud800 text on the wire, so the request body is built by hand
    # here with stdlib json.dumps (ensure_ascii=True, the default) to match
    # what actually reaches the backend.
    body = json.dumps({
        'text': 'Name: John \ud800 Smith', 'student_name': 'John Smith',
        'parent_names': [], 'family_names': [], 'organisation_names': [],
    })
    r = client.post('/api/text/detect', content=body.encode('utf-8'),
                     headers={'Content-Type': 'application/json'})
    assert r.status_code == 400
    assert 'character' in r.json()['detail'].lower()
    assert 'utf-8' not in r.json()['detail'].lower()
    assert 'codec' not in r.json()['detail'].lower()


def test_manual_pii_can_be_added_against_the_pasted_text():
    # Previously /api/pii/manual's exists()/page-count probes assumed a real
    # file and rejected PASTE_KEY with "File not found: <pasted-text>" — the
    # "Add a Missed Item" control in DocumentReview was silently broken for
    # every paste-mode user.
    detect()
    r = client.post('/api/pii/manual', json={
        'doc_path': PASTE_KEY, 'text': 'Acme School', 'page_num': 1,
        'category': 'Organisation name'})
    assert r.status_code == 200
    body = r.json()
    assert body['match']['text'] == 'Acme School'
    assert body['match']['page_num'] == 1
    assert body['match']['source'] == 'manual'


def test_manual_pii_round_trips_through_clean_for_pasted_text():
    # The thing that actually matters: a manually-added item must be appended
    # to the same cache /api/text/clean reads from, and must then be removed
    # from the output when its selection key is included — exactly like an
    # engine-found match (CLAUDE.md rule #31).
    text = SAMPLE + ' Ask Acme School for records.'
    r = detect(text=text)
    n = len(r.json()['documents'][0]['matches'])
    # Sanity: the engines don't already know about this organisation — the
    # test would be meaningless if they did.
    for m in r.json()['documents'][0]['matches']:
        assert m['text'] != 'Acme School'

    add = client.post('/api/pii/manual', json={
        'doc_path': PASTE_KEY, 'text': 'Acme School', 'page_num': 1,
        'category': 'Organisation name'})
    assert add.status_code == 200
    manual_index = add.json()['index']
    assert manual_index == n  # appended at the end, not inserted (rule #31)

    selected_keys = [f'{PASTE_KEY}_{i}' for i in range(n)] + [f'{PASTE_KEY}_{manual_index}']
    clean_r = client.post('/api/text/clean', json={
        'mode': 'redact', 'student_name': 'Billy Bob',
        'selected_keys': selected_keys,
        'parent_names': ['Jane Bob'], 'family_names': [],
        'organisation_names': [], 'person_roles': {},
        'person_custom_labels': {}, 'ignored_people': []})
    assert clean_r.status_code == 200
    assert 'Acme School' not in clean_r.json()['text']
    assert 'Billy Bob' not in clean_r.json()['text']


def test_manual_pii_still_rejects_a_real_missing_file():
    # The PASTE_KEY short-circuit must not weaken the exists() guard for real
    # paths — a doc_path that IS cached but no longer exists on disk (moved,
    # renamed, deleted) must still 400 rather than being treated like paste.
    fake_path = '/tmp/definitely-does-not-exist-12345.pdf'
    _detection_cache[fake_path] = {'matches': [], 'text_data': {'pages': {}, 'ocr_pages': []}}
    try:
        r = client.post('/api/pii/manual', json={
            'doc_path': fake_path, 'text': 'Some Name',
            'page_num': 1, 'category': 'Manual'})
        assert r.status_code == 400
        assert 'file not found' in r.json()['detail'].lower()
    finally:
        _detection_cache.pop(fake_path, None)


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


def clean(mode='redact', **over):
    return client.post('/api/text/clean', json=paste_body(mode, **over))


def test_blackout_removes_the_student_name():
    r = clean('redact')
    assert r.status_code == 200
    assert 'Billy Bob' not in r.json()['text']
    assert '█' in r.json()['text']
    assert r.json()['replacements'] > 0


def test_blackout_returns_no_key_entries():
    assert clean('redact').json()['key_entries'] == []


def test_deidentify_returns_labels_and_a_key():
    r = clean('deidentify')
    assert r.status_code == 200
    assert '[Student]' in r.json()['text']
    assert 'Billy Bob' not in r.json()['text']
    entries = {e['label']: e['real_name'] for e in r.json()['key_entries']}
    assert entries.get('[Student]') == 'Billy Bob'


def test_deselected_items_are_left_alone():
    r = clean('redact', selected_keys=[])
    assert r.json()['replacements'] == 0
    assert 'Billy Bob' in r.json()['text']


def test_clean_without_detection_returns_400():
    client.post('/api/text/discard')
    r = client.post('/api/text/clean', json={
        'mode': 'redact', 'student_name': 'Billy Bob', 'selected_keys': [],
        'parent_names': [], 'family_names': [], 'organisation_names': [],
        'person_roles': {}, 'person_custom_labels': {}, 'ignored_people': []})
    assert r.status_code == 400


def test_discard_clears_the_cache():
    detect()
    assert client.post('/api/text/discard').json()['discarded'] is True
    # Hand-built body, NOT the clean()/paste_body() helpers: paste_body() calls
    # detect() internally to compute selected_keys, which would silently
    # repopulate the very cache this test just discarded and the endpoint
    # would then return 200. Posting directly is the only way to prove the
    # cache is genuinely gone (mirrors test_clean_without_detection_returns_400).
    r = client.post('/api/text/clean', json={
        'mode': 'redact', 'student_name': 'Billy Bob', 'selected_keys': [],
        'parent_names': [], 'family_names': [], 'organisation_names': [],
        'person_roles': {}, 'person_custom_labels': {}, 'ignored_people': []})
    assert r.status_code == 400
    # Nothing left to discard a second time.
    assert client.post('/api/text/discard').json()['discarded'] is False


def test_saving_txt_writes_the_exact_text():
    out = Path(tempfile.mkdtemp()) / 'out.txt'
    r = client.post('/api/text/save', json={
        'text': 'Hello [Student].', 'path': str(out), 'kind': 'txt'})
    assert r.status_code == 200
    assert out.read_text(encoding='utf-8') == 'Hello [Student].'


def test_saving_pdf_produces_black_boxes_and_no_block_glyphs():
    out = Path(tempfile.mkdtemp()) / 'out.pdf'
    r = client.post('/api/text/save', json={
        'text': 'Name: ██████ attended.', 'path': str(out), 'kind': 'pdf'})
    assert r.status_code == 200
    doc = fitz.open(str(out))
    extracted = ''.join(p.get_text() for p in doc)
    drawings = doc[0].get_drawings()
    doc.close()
    assert '█' not in extracted and '?' not in extracted
    assert len(drawings) >= 1


def test_an_unknown_kind_is_rejected():
    out = Path(tempfile.mkdtemp()) / 'out.bin'
    r = client.post('/api/text/save', json={
        'text': 'x', 'path': str(out), 'kind': 'exe'})
    assert r.status_code == 400


def test_saving_pdf_with_unsupported_characters_warns_but_still_saves():
    # Defect A (e2e report): emoji/non-Latin-1 characters in the user's own
    # text silently became "?" in the saved PDF. The save must still
    # succeed -- it's a warning, not a failure -- but the response must say
    # which characters could not be shown.
    out = Path(tempfile.mkdtemp()) / 'out.pdf'
    r = client.post('/api/text/save', json={
        'text': 'Great work! 🎉 Name: ██████.', 'path': str(out), 'kind': 'pdf'})
    assert r.status_code == 200
    assert out.exists()
    assert '🎉' in r.json()['unsupported_characters']


def test_saving_pdf_with_only_latin1_text_reports_no_warning():
    out = Path(tempfile.mkdtemp()) / 'out.pdf'
    r = client.post('/api/text/save', json={
        'text': 'Café François attended.', 'path': str(out), 'kind': 'pdf'})
    assert r.status_code == 200
    assert r.json()['unsupported_characters'] == []


def test_saving_txt_never_reports_unsupported_characters():
    # The .txt path is UTF-8 all the way through -- no font, no limitation.
    out = Path(tempfile.mkdtemp()) / 'out.txt'
    r = client.post('/api/text/save', json={
        'text': 'Great work! 🎉 שלום', 'path': str(out), 'kind': 'txt'})
    assert r.status_code == 200
    assert r.json()['unsupported_characters'] == []
    assert out.read_text(encoding='utf-8') == 'Great work! 🎉 שלום'
