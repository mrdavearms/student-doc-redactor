import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import re

import pytest
from pseudonym_map import (
    ASSIGNABLE_ROLES,
    clean_person_name,
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
        assert label == "[Other person]"

    def test_classmate_surname_maps_to_the_classmate(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("Billy Chen")
        assert pmap.label_for("Chen", "Person name (NER variation)") == "[Other person]"

    def test_shared_given_name_resolves_to_the_student(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("Billy Chen")
        assert pmap.label_for("Billy", "Student name") == STUDENT_LABEL

    def test_full_names_stay_distinct_when_a_token_is_shared(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("Billy Chen")
        assert pmap.label_for("Billy Bob", "Student name") == STUDENT_LABEL
        assert pmap.label_for("Billy Chen", "Person name (NER)") == "[Other person]"

    def test_shared_surname_becomes_neutral_family_label(self):
        pmap = PseudonymMap(student_name="Billy Bob", parent_names=["Mrs Bob"])
        assert pmap.label_for("Bob", "Student name") == SHARED_SURNAME_LABEL

    def test_sibling_gets_own_label_but_shares_family_name(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        sibling = pmap.register_person("Sally Bob")
        assert sibling == "[Other person]"
        assert pmap.label_for("Sally", "Person name (NER variation)") == "[Other person]"
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
        assert not any(l.startswith("[Other person") for l, _ in pmap.key_entries())

    def test_unrelated_people_sharing_a_surname_are_distinct(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        a = pmap.register_person("Sarah Williams")
        b = pmap.register_person("John Williams")
        assert a != b
        assert pmap.label_for("Williams", "Person name (NER variation)") == SHARED_SURNAME_LABEL

    def test_person_numbering_is_stable_and_sequential(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        assert pmap.register_person("Sarah Williams") == "[Other person]"
        assert pmap.register_person("John Citizen") == "[Other person 2]"
        # Labels renumber as people are added; the map is authoritative, not the
        # return value of an earlier call.
        assert pmap.label_for("Sarah Williams", "Person name (NER)") == "[Other person 1]"


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
        assert pmap.label_for("Ada Kowalski", "Family member (user-provided)") == "[Family member]"

    def test_organisation_full_name_and_significant_words(self):
        pmap = PseudonymMap(student_name="Billy Bob",
                            organisation_names=["Riverside Primary School"])
        assert pmap.label_for("Riverside Primary School", "Organisation name") == "[Organisation]"
        assert pmap.label_for("Riverside", "Organisation name") == "[Organisation]"

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
        assert entries["[Parent]"] == "Mary Bloggs"

    def test_key_entries_include_discovered_people(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("Sarah Williams")
        assert ("[Other person]", "Sarah Williams") in pmap.key_entries()

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


# ---------------------------------------------------------------------------
# Junk candidates from real PDF extraction (regression: found by e2e run)
# ---------------------------------------------------------------------------

class TestJunkPersonCandidates:
    """
    PDF text extraction hands NER run-together spans, and form labels get
    flagged as names. Registering those invents bogus [Person N] entries and
    gives one child two different labels in the same document.
    """

    def test_extraction_span_is_not_a_person(self):
        assert clean_person_name("Billy Bob        Date of Birth") is None

    def test_form_label_is_not_a_person(self):
        for label in ["Email", "Phone", "Date of Birth", "Student", "Contact"]:
            assert clean_person_name(label) is None, label

    def test_name_with_digits_is_not_a_person(self):
        assert clean_person_name("Billy Bob 2024") is None

    def test_long_span_is_not_a_person(self):
        assert clean_person_name("Billy Bob and his mother Mary Bob") is None

    def test_ordinary_names_survive(self):
        assert clean_person_name("Billy Bob") == "Billy Bob"
        assert clean_person_name("  Sarah   Williams ") == "Sarah Williams"
        assert clean_person_name("O'Brien") == "O'Brien"
        assert clean_person_name("Smith-Jones") == "Smith-Jones"

    def test_honorific_is_stripped(self):
        assert clean_person_name("Ms Williams") == "Williams"
        assert clean_person_name("Dr. Sarah Williams") == "Sarah Williams"

    def test_honorific_form_merges_with_full_name(self):
        """'Ms Williams' and 'Sarah Williams' are one teacher, not two."""
        pmap = PseudonymMap(student_name="Billy Bob")
        first = pmap.register_person("Sarah Williams")
        assert pmap.register_person("Ms Williams") == first

    def test_junk_span_mints_no_person(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("Billy Bob        Date of Birth")
        assert not any(l.startswith("[Other person") for l, _ in pmap.key_entries())

    def test_span_containing_a_known_name_resolves_to_that_person(self):
        """The student must not become [name] on the one line NER over-grabbed."""
        pmap = PseudonymMap(student_name="Billy Bob")
        label = pmap.label_for("Billy Bob        Date of Birth", "Person name (NER)")
        assert label == STUDENT_LABEL

    def test_unknown_span_still_falls_back_safely(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        assert pmap.label_for("Someone Entirely Else", "Person name (NER)") == "[name]"


class TestMergeBookkeeping:
    """
    Regression: a merge used to be forgotten the moment it returned. The new
    surface form was never recorded against the owner, so a later variation of
    it minted a SECOND [Person N] for the same human — two labels in the output
    and two rows in the key file.
    """

    def test_three_written_forms_of_one_person_share_a_label(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        a = pmap.register_person("S. Williams")
        b = pmap.register_person("Sarah Williams")
        c = pmap.register_person("Sarah W.")
        assert a == b == c

    def test_label_for_agrees_across_all_forms(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("S. Williams")
        pmap.register_person("Sarah Williams")
        pmap.register_person("Sarah W.")
        labels = {
            pmap.label_for(t, "Person name (NER)")
            for t in ["S. Williams", "Sarah Williams", "Sarah W.", "Sarah", "Williams"]
        }
        assert len(labels) == 1, f"one person resolved to several labels: {labels}"

    def test_one_person_is_one_key_entry(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("S. Williams")
        pmap.register_person("Sarah Williams")
        pmap.register_person("Sarah W.")
        people = [l for l, _ in pmap.key_entries() if l.startswith("[Other person")]
        assert people == ["[Other person]"]

    def test_key_file_shows_the_fullest_form_of_the_name(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("S. Williams")
        pmap.register_person("Sarah Williams")
        assert dict(pmap.key_entries())["[Other person]"] == "Sarah Williams"

    def test_merging_does_not_break_the_shared_surname_rule(self):
        """The merge must not claim a token someone else already owns."""
        pmap = PseudonymMap(student_name="Billy Bob", parent_names=["Mrs Bob"])
        pmap.register_person("Bob")
        assert pmap.label_for("Bob", "Student name") == SHARED_SURNAME_LABEL

    def test_distinct_people_still_stay_distinct_after_merging(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("S. Williams")
        pmap.register_person("Sarah Williams")
        other = pmap.register_person("John Citizen")
        assert other == "[Other person 2]"


# ---------------------------------------------------------------------------
# Roles: proposed by the tool, confirmed by the user
# ---------------------------------------------------------------------------

class TestRoleAssignment:

    def test_single_holder_of_a_role_is_unnumbered(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("Sarah Williams")
        assert pmap.assign_role("Sarah Williams", "teacher") == "[Teacher]"

    def test_several_holders_are_numbered(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        for name in ["Sarah Williams", "John Citizen", "Ada Kowalski"]:
            pmap.register_person(name)
            pmap.assign_role(name, "teacher")
        labels = [pmap.label_for(n, "Person name (NER)")
                  for n in ["Sarah Williams", "John Citizen", "Ada Kowalski"]]
        assert labels == ["[Teacher 1]", "[Teacher 2]", "[Teacher 3]"]

    def test_assignment_through_a_variation_hits_the_right_person(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("Sarah Williams")
        pmap.assign_role("Ms Williams", "health")
        assert pmap.label_for("Sarah Williams", "Person name (NER)") == "[Health professional]"

    def test_the_student_can_never_be_reclassified(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        assert pmap.assign_role("Billy Bob", "teacher") is None
        assert pmap.label_for("Billy Bob", "Student name") == STUDENT_LABEL

    def test_reassignment_renumbers_the_people_left_behind(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        for n in ["Sarah Williams", "John Citizen"]:
            pmap.register_person(n)
            pmap.assign_role(n, "teacher")
        assert pmap.label_for("Sarah Williams", "Person name (NER)") == "[Teacher 1]"
        # Moving one out leaves the other as the sole teacher — unnumbered.
        pmap.assign_role("John Citizen", "health")
        assert pmap.label_for("Sarah Williams", "Person name (NER)") == "[Teacher]"
        assert pmap.label_for("John Citizen", "Person name (NER)") == "[Health professional]"

    def test_discovered_people_default_to_other_person(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("Sarah Williams")
        assert pmap.label_for("Sarah Williams", "Person name (NER)") == "[Other person]"

    def test_entered_parents_start_classified_as_parents(self):
        pmap = PseudonymMap(student_name="Billy Bob", parent_names=["Mary Bloggs"])
        assert pmap.label_for("Mary Bloggs", "Parent/Guardian (user-provided)") == "[Parent]"

    def test_people_list_excludes_the_student_and_organisations(self):
        pmap = PseudonymMap(student_name="Billy Bob", parent_names=["Mary Bloggs"],
                            organisation_names=["Riverside Primary School"])
        pmap.register_person("Sarah Williams")
        names = [p.full_name for p in pmap.people()]
        assert "Billy Bob" not in names
        assert "Riverside Primary School" not in names
        assert set(names) == {"Mary Bloggs", "Sarah Williams"}

    def test_people_list_reports_where_each_person_came_from(self):
        pmap = PseudonymMap(student_name="Billy Bob", parent_names=["Mary Bloggs"])
        pmap.register_person("Sarah Williams")
        sources = {p.full_name: p.source for p in pmap.people()}
        assert sources == {"Mary Bloggs": "entered", "Sarah Williams": "detected"}


class TestCustomRoleNumberingNamespace:
    """
    Numbering is keyed on the rendered stem across built-in AND custom roles.
    Bucketing per role key would let two people emit the same bare label and
    become indistinguishable — the rule #44 meaning failure, user-induced.
    """

    def test_two_identical_custom_roles_are_numbered_apart(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        for n in ["Sarah Williams", "John Citizen"]:
            pmap.register_person(n)
            pmap.assign_role(n, "health", custom_label="Speech pathologist")
        a = pmap.label_for("Sarah Williams", "Person name (NER)")
        b = pmap.label_for("John Citizen", "Person name (NER)")
        assert a != b
        assert {a, b} == {"[Speech pathologist 1]", "[Speech pathologist 2]"}

    def test_custom_text_matching_a_builtin_label_shares_its_numbering(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("Sarah Williams")
        pmap.register_person("John Citizen")
        pmap.assign_role("Sarah Williams", "health")                      # [Health professional]
        pmap.assign_role("John Citizen", "other", custom_label="Health professional")
        a = pmap.label_for("Sarah Williams", "Person name (NER)")
        b = pmap.label_for("John Citizen", "Person name (NER)")
        assert a != b, "identical rendered stems must not collide"

    def test_custom_role_is_case_normalised_for_collision_purposes(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        for n, text in [("Sarah Williams", "speech pathologist"),
                        ("John Citizen", "Speech Pathologist")]:
            pmap.register_person(n)
            pmap.assign_role(n, "other", custom_label=text)
        a = pmap.label_for("Sarah Williams", "Person name (NER)")
        b = pmap.label_for("John Citizen", "Person name (NER)")
        assert a != b


class TestCustomRoleSanitisation:
    """A custom role is free text going straight into a label — the one place
    rule #42 could be bypassed by an honest mistake."""

    def test_plain_job_title_is_accepted(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        assert pmap.sanitise_custom_role("speech pathologist") == "Speech pathologist"

    def test_role_containing_the_students_name_is_rejected(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        assert pmap.sanitise_custom_role("Billy's mum") is None

    def test_role_containing_a_DIFFERENT_persons_name_is_rejected(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("Sarah Williams")
        assert pmap.sanitise_custom_role("Sarah's colleague") is None

    def test_role_containing_an_organisation_name_is_rejected(self):
        pmap = PseudonymMap(student_name="Billy Bob",
                            organisation_names=["Riverside Primary School"])
        assert pmap.sanitise_custom_role("Riverside staff") is None

    def test_whole_word_check_does_not_reject_innocent_text(self):
        """'Ann' inside 'Annual' is not a leak — same rule as verification."""
        pmap = PseudonymMap(student_name="Ann Smith")
        assert pmap.sanitise_custom_role("Annual reviewer") == "Annual reviewer"

    def test_digits_are_rejected(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        assert pmap.sanitise_custom_role("Teacher 2024") is None

    def test_overlong_text_is_rejected(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        assert pmap.sanitise_custom_role("x" * 40) is None

    def test_rejected_custom_role_falls_back_to_other_person(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("Sarah Williams")
        pmap.assign_role("Sarah Williams", "teacher", custom_label="Billy's teacher")
        assert pmap.label_for("Sarah Williams", "Person name (NER)") == "[Other person]"

    def test_no_role_label_ever_leaks_a_name(self):
        """Rule #42, extended across every role including customs."""
        pmap = PseudonymMap(student_name="Billy Bob", parent_names=["Mary Bloggs"])
        pmap.register_person("Sarah Williams")
        for role in ASSIGNABLE_ROLES:
            pmap.assign_role("Sarah Williams", role)
            label = pmap.label_for("Sarah Williams", "Person name (NER)").lower()
            for word in ["billy", "bob", "mary", "bloggs", "sarah", "williams"]:
                assert word not in label, f"role {role} leaked {word}"
