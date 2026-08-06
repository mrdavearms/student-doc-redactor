import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import tempfile
from pathlib import Path

import fitz
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

REPORT = [
    "Student: Billy Bob",
    "His classroom teacher, Sarah Williams, reports steady progress.",
    "Speech pathologist Ada Kowalski completed the assessment.",
    "His NDIS support worker, John Citizen, attends fortnightly.",
    "Billy's mother, Mary Bob, attended the meeting.",
]


def _make_pdf(path, lines):
    doc = fitz.open()
    page = doc.new_page()
    y = 90
    for line in lines:
        page.insert_text((60, y), line, fontsize=11)
        y += 18
    doc.save(str(path))
    doc.close()


def _setup(tmp, lines=None):
    pdf = Path(tmp) / "report.pdf"
    _make_pdf(pdf, lines or REPORT)
    det = client.post("/api/pii/detect", json={
        "pdf_paths": [str(pdf)], "student_name": "Billy Bob",
        "parent_names": ["Mary Bob"], "family_names": [], "organisation_names": [],
    })
    assert det.status_code == 200, det.text
    doc0 = det.json()["documents"][0]
    return pdf, doc0, [f"{pdf}_{i}" for i in range(len(doc0["matches"]))]


def _body(tmp, pdf, selected, **extra):
    body = {
        "folder_path": tmp, "student_name": "Billy Bob",
        "parent_names": ["Mary Bob"], "family_names": [], "organisation_names": [],
        "documents": [str(pdf)], "selected_keys": selected,
    }
    body.update(extra)
    return body


def test_people_endpoint_lists_discovered_people_with_suggestions():
    with tempfile.TemporaryDirectory() as tmp:
        pdf, _, selected = _setup(tmp)
        res = client.post("/api/deidentify/people", json=_body(tmp, pdf, selected))
        assert res.status_code == 200, res.text
        data = res.json()

        assert data["people"], "expected at least one person"
        for person in data["people"]:
            assert set(person) >= {
                "full_name", "label", "role", "suggested_role",
                "confidence", "evidence", "snippet", "occurrences", "source",
            }
        # The dropdown vocabulary comes from the backend.
        assert any(r["key"] == "teacher" for r in data["roles"])


def test_the_student_is_never_offered_for_classification():
    with tempfile.TemporaryDirectory() as tmp:
        pdf, _, selected = _setup(tmp)
        res = client.post("/api/deidentify/people", json=_body(tmp, pdf, selected))
        names = [p["full_name"] for p in res.json()["people"]]
        assert "Billy Bob" not in names


def test_entered_parent_is_prefilled_not_guessed_at():
    with tempfile.TemporaryDirectory() as tmp:
        pdf, _, selected = _setup(tmp)
        res = client.post("/api/deidentify/people", json=_body(tmp, pdf, selected))
        entered = [p for p in res.json()["people"] if p["source"] == "entered"]
        assert entered, "the parent typed into the form should appear"
        assert all(p["confidence"] == "entered" for p in entered)
        assert all(p["role"] == "parent" for p in entered)


def test_a_deselected_persons_only_occurrence_removes_them_from_the_list():
    """Offering someone whose text will never be replaced would mislead."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf, doc0, selected = _setup(tmp)

        everyone = client.post("/api/deidentify/people",
                               json=_body(tmp, pdf, selected)).json()["people"]
        detected = [p for p in everyone if p["source"] == "detected"]
        assert detected, "need a detected person for this test"
        target = detected[0]["full_name"]

        # Deselect every match that resolves to that person.
        keep = [
            key for key, m in zip(selected, doc0["matches"])
            if m["text"].lower() not in target.lower()
            and target.lower() not in m["text"].lower()
        ]
        after = client.post("/api/deidentify/people",
                            json=_body(tmp, pdf, keep)).json()["people"]
        assert target not in [p["full_name"] for p in after]


def test_roles_reach_the_output_labels():
    with tempfile.TemporaryDirectory() as tmp:
        pdf, _, selected = _setup(tmp)
        people = client.post("/api/deidentify/people",
                             json=_body(tmp, pdf, selected)).json()["people"]
        detected = [p["full_name"] for p in people if p["source"] == "detected"]
        assert detected

        roles = {detected[0]: "teacher"}
        res = client.post("/api/deidentify",
                          json=_body(tmp, pdf, selected, person_roles=roles))
        assert res.status_code == 200, res.text
        out = Path(res.json()["document_results"][0]["output_path"])
        body = out.read_text(encoding="utf-8")
        assert "[Teacher]" in body
        assert detected[0].split()[0] not in body


def test_label_preview_matches_what_the_run_produces():
    """The preview endpoint exists so the UI never reimplements numbering."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf, _, selected = _setup(tmp)
        people = client.post("/api/deidentify/people",
                             json=_body(tmp, pdf, selected)).json()["people"]
        detected = [p["full_name"] for p in people if p["source"] == "detected"]
        roles = {name: "teacher" for name in detected[:2]}

        preview = client.post("/api/deidentify/labels",
                              json=_body(tmp, pdf, selected, person_roles=roles))
        assert preview.status_code == 200, preview.text
        labels = preview.json()["labels"]

        run = client.post("/api/deidentify",
                          json=_body(tmp, pdf, selected, person_roles=roles))
        body = Path(run.json()["document_results"][0]["output_path"]).read_text()
        for name in roles:
            assert labels[name] in body, f"preview said {labels[name]} for {name}"


def test_reassigning_one_person_renumbers_the_others():
    with tempfile.TemporaryDirectory() as tmp:
        pdf, _, selected = _setup(tmp)
        people = client.post("/api/deidentify/people",
                             json=_body(tmp, pdf, selected)).json()["people"]
        detected = [p["full_name"] for p in people if p["source"] == "detected"]
        if len(detected) < 2:
            return  # not enough people in this fixture

        both = {n: "teacher" for n in detected[:2]}
        labels_both = client.post("/api/deidentify/labels",
                                  json=_body(tmp, pdf, selected, person_roles=both)
                                  ).json()["labels"]
        assert labels_both[detected[0]] == "[Teacher 1]"

        one = {detected[0]: "teacher", detected[1]: "health"}
        labels_one = client.post("/api/deidentify/labels",
                                 json=_body(tmp, pdf, selected, person_roles=one)
                                 ).json()["labels"]
        # Sole remaining teacher loses its number.
        assert labels_one[detected[0]] == "[Teacher]"


def test_ignored_person_text_is_still_replaced():
    """Marking NER junk 'not a person' must not leave the text in the output."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf, _, selected = _setup(tmp)
        people = client.post("/api/deidentify/people",
                             json=_body(tmp, pdf, selected)).json()["people"]
        detected = [p["full_name"] for p in people if p["source"] == "detected"]
        assert detected

        res = client.post("/api/deidentify",
                          json=_body(tmp, pdf, selected, ignored_people=[detected[0]]))
        assert res.status_code == 200, res.text
        body = Path(res.json()["document_results"][0]["output_path"]).read_text()
        for word in detected[0].split():
            if len(word) > 2:
                assert word not in body, f"ignoring a person leaked {word!r}"


def test_custom_role_containing_a_name_falls_back_safely():
    with tempfile.TemporaryDirectory() as tmp:
        pdf, _, selected = _setup(tmp)
        people = client.post("/api/deidentify/people",
                             json=_body(tmp, pdf, selected)).json()["people"]
        detected = [p["full_name"] for p in people if p["source"] == "detected"]
        assert detected

        res = client.post("/api/deidentify/labels", json=_body(
            tmp, pdf, selected,
            person_roles={detected[0]: "teacher"},
            person_custom_labels={detected[0]: "Billy's teacher"},
        ))
        assert res.status_code == 200, res.text
        assert "Billy" not in res.json()["labels"][detected[0]]


def test_audit_log_still_carries_no_real_names_with_roles():
    with tempfile.TemporaryDirectory() as tmp:
        pdf, _, selected = _setup(tmp)
        people = client.post("/api/deidentify/people",
                             json=_body(tmp, pdf, selected)).json()["people"]
        detected = [p["full_name"] for p in people if p["source"] == "detected"]
        roles = {n: "teacher" for n in detected}

        res = client.post("/api/deidentify",
                          json=_body(tmp, pdf, selected, person_roles=roles))
        log = res.json()["log_content"]
        for leaked in ["Billy", "Bob", "Mary", "Sarah", "Williams", "Kowalski", "Citizen"]:
            assert leaked not in log, f"audit log leaked {leaked}"


def test_people_endpoint_400s_on_a_cold_cache():
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "never_detected.pdf"
        _make_pdf(pdf, ["Billy Bob is here."])
        res = client.post("/api/deidentify/people", json=_body(tmp, pdf, []))
        assert res.status_code == 400
        assert "no cached detection data" in res.json()["detail"].lower()


def test_labels_endpoint_400s_on_a_cold_cache():
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "never_detected.pdf"
        _make_pdf(pdf, ["Billy Bob is here."])
        res = client.post("/api/deidentify/labels", json=_body(tmp, pdf, []))
        assert res.status_code == 400
        assert "no cached detection data" in res.json()["detail"].lower()
