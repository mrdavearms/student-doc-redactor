import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import re

import pytest
from pseudonym_map import (
    PseudonymMap,
    STUDENT_LABEL,
    SHARED_SURNAME_LABEL,
    is_person_category,
)


# ---------------------------------------------------------------------------
# The governing privacy invariant
# ---------------------------------------------------------------------------

class TestNoIdentityLeaksIntoLabels:
    """
    A label must never carry information derived from the real name. Initials
    like [Student(BB)] are barely pseudonymous in a small school community.
    """

    def _assert_label_is_clean(self, label: str, real_name: str):
        label_lower = label.lower()
        for word in real_name.split():
            if len(word) >= 2:
                assert word.lower() not in label_lower, (
                    f"label {label!r} leaks name fragment {word!r}"
                )
        # No initials pattern either: "BB", "B.B.", "B B" from "Billy Bob"
        initials = ''.join(p[0] for p in real_name.split() if p)
        if len(initials) >= 2:
            squashed = re.sub(r'[^a-z]', '', label_lower)
            assert initials.lower() not in squashed, (
                f"label {label!r} leaks initials {initials!r}"
            )

    def test_student_label_carries_nothing_from_the_name(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        assert pmap.label_for("Billy Bob", "Student name") == STUDENT_LABEL
        self._assert_label_is_clean(STUDENT_LABEL, "Billy Bob")

    def test_every_key_entry_label_is_clean(self):
        pmap = PseudonymMap(
            student_name="Billy Bob",
            parent_names=["Mary Bloggs"],
            family_names=["Ada Kowalski"],
            organisation_names=["Riverside Primary School"],
        )
        pmap.register_person("Sarah Williams")
        for label, real_name in pmap.key_entries():
            self._assert_label_is_clean(label, real_name)

    def test_all_variations_map_to_clean_labels(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        for text in ["Billy Bob", "Billy", "Bob", "B. Bob", "Billy B."]:
            label = pmap.label_for(text, "Student name")
            self._assert_label_is_clean(label, "Billy Bob")


# ---------------------------------------------------------------------------
# Identity: multiple people, multiple students in one file
# ---------------------------------------------------------------------------

class TestPersonIdentity:

    def test_classmate_sharing_a_first_name_is_a_separate_person(self):
        """The bug this rule exists for: Billy Chen must not become [Student]."""
        pmap = PseudonymMap(student_name="Billy Bob")
        label = pmap.register_person("Billy Chen")
        assert label != STUDENT_LABEL
        assert label == "[Person 1]"

    def test_classmate_surname_maps_to_the_classmate(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("Billy Chen")
        assert pmap.label_for("Chen", "Person name (NER variation)") == "[Person 1]"

    def test_shared_given_name_resolves_to_the_student(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("Billy Chen")
        assert pmap.label_for("Billy", "Student name") == STUDENT_LABEL

    def test_full_names_stay_distinct_when_a_token_is_shared(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("Billy Chen")
        assert pmap.label_for("Billy Bob", "Student name") == STUDENT_LABEL
        assert pmap.label_for("Billy Chen", "Person name (NER)") == "[Person 1]"

    def test_shared_surname_becomes_neutral_family_label(self):
        pmap = PseudonymMap(student_name="Billy Bob", parent_names=["Mrs Bob"])
        assert pmap.label_for("Bob", "Student name") == SHARED_SURNAME_LABEL

    def test_sibling_gets_own_label_but_shares_family_name(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        sibling = pmap.register_person("Sally Bob")
        assert sibling == "[Person 1]"
        assert pmap.label_for("Sally", "Person name (NER variation)") == "[Person 1]"
        assert pmap.label_for("Bob", "Student name") == SHARED_SURNAME_LABEL

    def test_initialised_form_merges_with_full_name(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        first = pmap.register_person("Sarah Williams")
        second = pmap.register_person("S. Williams")
        assert first == second

    def test_initialised_form_merges_in_either_discovery_order(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        first = pmap.register_person("S. Williams")
        second = pmap.register_person("Sarah Williams")
        assert first == second

    def test_bare_first_name_resolves_to_existing_owner(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        assert pmap.register_person("Billy") == STUDENT_LABEL

    def test_ner_hit_on_entered_family_name_does_not_mint_a_person(self):
        pmap = PseudonymMap(student_name="Billy Bob", family_names=["Bob"])
        label = pmap.register_person("Bob")
        assert label in (STUDENT_LABEL, "[Family member 1]")
        assert not any(l.startswith("[Person ") for l, _ in pmap.key_entries())

    def test_unrelated_people_sharing_a_surname_are_distinct(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        a = pmap.register_person("Sarah Williams")
        b = pmap.register_person("John Williams")
        assert a != b
        assert pmap.label_for("Williams", "Person name (NER variation)") == SHARED_SURNAME_LABEL

    def test_person_numbering_is_stable_and_sequential(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        assert pmap.register_person("Sarah Williams") == "[Person 1]"
        assert pmap.register_person("John Citizen") == "[Person 2]"
        assert pmap.register_person("Sarah Williams") == "[Person 1]"


# ---------------------------------------------------------------------------
# Labels for user-entered people, organisations and structured PII
# ---------------------------------------------------------------------------

class TestLabelAssignment:

    def test_parents_numbered_in_entry_order(self):
        pmap = PseudonymMap(student_name="Billy Bob",
                            parent_names=["Mary Bloggs", "Peter Citizen"])
        assert pmap.label_for("Mary Bloggs", "Parent/Guardian (user-provided)") == "[Parent 1]"
        assert pmap.label_for("Peter Citizen", "Parent/Guardian (user-provided)") == "[Parent 2]"

    def test_family_members_numbered_in_entry_order(self):
        pmap = PseudonymMap(student_name="Billy Bob",
                            family_names=["Ada Kowalski"])
        assert pmap.label_for("Ada Kowalski", "Family member (user-provided)") == "[Family member 1]"

    def test_organisation_full_name_and_significant_words(self):
        pmap = PseudonymMap(student_name="Billy Bob",
                            organisation_names=["Riverside Primary School"])
        assert pmap.label_for("Riverside Primary School", "Organisation name") == "[Organisation 1]"
        assert pmap.label_for("Riverside", "Organisation name") == "[Organisation 1]"

    def test_generic_org_words_are_not_claimed(self):
        pmap = PseudonymMap(student_name="Billy Bob",
                            organisation_names=["Riverside Primary School"])
        # 'School' is generic — it must not become an organisation variation.
        assert pmap.label_for("School", "Organisation name") == "[organisation]"

    def test_nickname_maps_to_student(self):
        pmap = PseudonymMap(student_name="William Chen")
        assert pmap.label_for("Billy", "Student name (nickname)") == STUDENT_LABEL

    def test_short_student_name_is_preserved(self):
        pmap = PseudonymMap(student_name="Jo")
        assert pmap.label_for("Jo", "Student name") == STUDENT_LABEL

    def test_possessive_form_resolves(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        assert pmap.label_for("Billy's", "Student name") == STUDENT_LABEL

    @pytest.mark.parametrize("category,expected", [
        ("Phone number", "[phone]"),
        ("Email address", "[email]"),
        ("Address", "[address]"),
        ("Date of birth", "[date of birth]"),
        ("Medicare number", "[Medicare number]"),
        ("Student ID", "[student ID]"),
        ("Centrelink CRN", "[Centrelink CRN]"),
        ("NDIS number", "[NDIS number]"),
        ("ABN", "[ABN]"),
        ("Passport number", "[passport number]"),
    ])
    def test_structured_categories(self, category, expected):
        pmap = PseudonymMap(student_name="Billy Bob")
        assert pmap.label_for("0412 345 678", category) == expected

    def test_unknown_name_category_falls_back_to_generic_name(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        assert pmap.label_for("Someone Else", "Parent/family (contextual)") == "[name]"

    def test_completely_unknown_category_falls_back_to_redacted(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        assert pmap.label_for("XYZ123", "Some future category") == "[redacted]"

    def test_manual_items_are_never_silently_skipped(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        assert pmap.label_for("Anything", "Manual") != ""


# ---------------------------------------------------------------------------
# Key file content
# ---------------------------------------------------------------------------

class TestKeyEntriesAndNotes:

    def test_key_entries_use_original_full_names(self):
        pmap = PseudonymMap(student_name="Billy Bob", parent_names=["Mary Bloggs"])
        entries = dict(pmap.key_entries())
        assert entries[STUDENT_LABEL] == "Billy Bob"
        assert entries["[Parent 1]"] == "Mary Bloggs"

    def test_key_entries_include_discovered_people(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("Sarah Williams")
        assert ("[Person 1]", "Sarah Williams") in pmap.key_entries()

    def test_ambiguity_note_records_shared_first_name(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("Billy Chen")
        notes = " ".join(pmap.ambiguity_notes())
        assert "billy" in notes.lower()
        assert "Billy Chen" in notes
        assert STUDENT_LABEL in notes

    def test_no_ambiguity_notes_when_nothing_is_shared(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("Sarah Williams")
        assert pmap.ambiguity_notes() == []


class TestIsPersonCategory:

    @pytest.mark.parametrize("category", [
        "Student name", "Person name (NER)", "Person name (NER variation)",
        "Parent/Guardian (user-provided)", "Family member (user-provided)",
        "Parent/family (contextual)", "Student name (nickname)",
    ])
    def test_person_categories(self, category):
        assert is_person_category(category)

    @pytest.mark.parametrize("category", [
        "Organisation name", "Phone number", "Email address", "Address", "ABN",
    ])
    def test_non_person_categories(self, category):
        assert not is_person_category(category)
