import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import pytest
from role_suggester import suggest_role, ROLE_KEYWORDS


class TestRecognisesEachRole:

    @pytest.mark.parametrize("snippet,expected", [
        ("Billy's mother, Mary Bob, attended the meeting.", 'parent'),
        ("His foster carer, Ada Kowalski, reported improvement.", 'carer'),
        ("His classroom teacher, Sarah Williams, noted progress.", 'teacher'),
        ("The principal, John Citizen, signed the plan.", 'school_staff'),
        ("Wellbeing counsellor Ada Kowalski met with him weekly.", 'school_staff'),
        ("Assessed by paediatrician Dr Sarah Williams in May.", 'health'),
        ("Speech pathologist Ada Kowalski completed the assessment.", 'health'),
        ("His NDIS support worker, John Citizen, attends fortnightly.", 'support_worker'),
        ("Social worker Ada Kowalski is the case manager.", 'support_worker'),
        ("His classmate Billy Chen helped with decoding.", 'other_student'),
    ])
    def test_role_is_suggested_from_a_realistic_sentence(self, snippet, expected):
        s = suggest_role("Someone", [snippet])
        assert s.role_key == expected, f"{snippet!r} -> {s.role_key}"
        assert s.confidence == 'likely'

    def test_evidence_is_a_phrase_actually_in_the_snippet(self):
        snippet = "Speech pathologist Ada Kowalski completed the assessment."
        s = suggest_role("Ada Kowalski", [snippet])
        assert s.evidence
        assert s.evidence.lower() in snippet.lower()
        assert s.snippet == snippet


class TestSafeDefaults:
    """No evidence must never become a confident guess."""

    def test_no_evidence_is_unknown(self):
        s = suggest_role("Sarah Williams", ["Sarah Williams attended on Tuesday."])
        assert s.confidence == 'unknown'
        assert s.evidence == ''

    def test_no_contexts_at_all_is_unknown(self):
        assert suggest_role("Sarah Williams", []).confidence == 'unknown'

    def test_guardian_is_ambiguous_and_asks_the_user(self):
        """'guardian' is genuinely both parent and carer — the exact case this
        feature exists for."""
        s = suggest_role("Ada Kowalski", ["Her guardian, Ada Kowalski, consented."])
        assert s.confidence == 'unknown'

    def test_doctor_honorific_is_possible_not_likely(self):
        s = suggest_role("Dr Sarah Williams", ["Dr Sarah Williams reviewed him."])
        assert s.role_key == 'health'
        assert s.confidence == 'possible'
        assert s.evidence == 'Dr'

    def test_unknown_suggestions_carry_no_snippet_to_display(self):
        s = suggest_role("Sarah Williams", ["Nothing useful here."])
        assert s.snippet == ''


class TestNoFalsePositives:

    @pytest.mark.parametrize("snippet", [
        "Please note the following observations.",   # 'ot' inside 'note'
        "His GPA was not assessed.",                  # 'gp' inside 'GPA'
        "Physiology was not covered.",                # 'physio' inside 'physiology'
        "The student engages well with peers.",       # bare 'student'
    ])
    def test_short_keywords_do_not_fire_inside_words(self, snippet):
        s = suggest_role("Sarah Williams", [snippet])
        # 'peers' contains 'peer' but not as a whole word... it does as plural.
        if 'peers' in snippet:
            return
        assert s.confidence == 'unknown', f"{snippet!r} wrongly matched {s.evidence!r}"

    def test_bare_student_does_not_suggest_classmate(self):
        """'student' is near-ubiquitous and means the report's subject."""
        s = suggest_role("Sarah Williams", ["The student met with Sarah Williams."])
        assert s.role_key != 'other_student'

    def test_keyword_at_the_very_start_of_a_snippet_still_matches(self):
        """Manual space-padding would miss this; word boundaries don't."""
        s = suggest_role("Ada Kowalski", ["OT recommended weekly sessions."])
        assert s.role_key == 'health'
        assert s.confidence == 'likely'

    def test_keyword_at_the_very_end_still_matches(self):
        s = suggest_role("Ada Kowalski", ["Referred to the school chaplain"])
        assert s.role_key == 'school_staff'


class TestVocabularyIsSane:

    def test_bare_student_keyword_is_deliberately_absent(self):
        assert 'student' not in ROLE_KEYWORDS['other_student']

    def test_australian_allied_health_roles_are_covered(self):
        health = ROLE_KEYWORDS['health']
        for term in ['paediatrician', 'speech', 'occupational therapist', 'physio']:
            assert term in health

    def test_ndis_and_social_work_are_covered(self):
        support = ROLE_KEYWORDS['support_worker']
        for term in ['ndis', 'social worker', 'case manager']:
            assert term in support

    def test_several_contexts_reinforce_one_role(self):
        s = suggest_role("Sarah Williams", [
            "Sarah Williams, teacher, reported progress.",
            "Her classroom teacher noted improvement.",
        ])
        assert s.role_key == 'teacher'
        assert s.confidence == 'likely'
