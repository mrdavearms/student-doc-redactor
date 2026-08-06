import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import pytest
from pii_detector import PIIMatch
from pseudonym_map import PseudonymMap, STUDENT_LABEL
from text_deidentifier import (
    deidentify_text,
    verify_deidentified,
    fuzzy_leftovers,
    strip_labels,
)


def match(text, category='Student name', page_num=1, line_num=1):
    return PIIMatch(
        text=text, category=category, confidence=0.95,
        page_num=page_num, line_num=line_num, context=text,
    )


# ---------------------------------------------------------------------------
# Replacement
# ---------------------------------------------------------------------------

class TestReplacement:

    def test_full_name_replaced_with_label(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        out, count = deidentify_text("Billy Bob is in Year 3.", [match("Billy Bob")], pmap)
        assert out == f"{STUDENT_LABEL} is in Year 3."
        assert count == 1

    def test_longest_match_wins(self):
        """'Billy Bob' must be consumed before a lone 'Billy' can split it."""
        pmap = PseudonymMap(student_name="Billy Bob")
        matches = [match("Billy"), match("Billy Bob"), match("Bob")]
        out, _ = deidentify_text("Billy Bob did well.", matches, pmap)
        assert out == f"{STUDENT_LABEL} did well."

    def test_first_name_alone_still_replaced(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        out, _ = deidentify_text("Billy did well.", [match("Billy")], pmap)
        assert out == f"{STUDENT_LABEL} did well."

    def test_possessive_keeps_the_apostrophe(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        out, _ = deidentify_text("Billy's reading improved.", [match("Billy")], pmap)
        assert out == f"{STUDENT_LABEL}'s reading improved."

    def test_case_insensitive_leaves_no_trace(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        out, count = deidentify_text("BILLY and billy and Billy", [match("Billy")], pmap)
        assert "billy" not in out.lower()
        assert count == 3

    def test_not_matched_inside_a_longer_word(self):
        pmap = PseudonymMap(student_name="Ann Smith")
        out, count = deidentify_text("The annual report for Ann.", [match("Ann")], pmap)
        assert out.startswith("The annual report")
        assert count == 1

    def test_pii_at_start_and_end_of_text(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        out, count = deidentify_text("Billy", [match("Billy")], pmap)
        assert out == STUDENT_LABEL
        assert count == 1

    def test_email_replaced_exactly(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        out, _ = deidentify_text(
            "Contact billy@example.com today.",
            [match("billy@example.com", "Email address")], pmap,
        )
        assert out == "Contact [email] today."

    def test_phone_replaced(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        out, _ = deidentify_text(
            "Call 0412 345 678 now.",
            [match("0412 345 678", "Phone number")], pmap,
        )
        assert out == "Call [phone] now."

    def test_hyphenated_surname(self):
        pmap = PseudonymMap(student_name="Sarah Smith-Jones")
        out, _ = deidentify_text(
            "Sarah Smith-Jones attended.",
            [match("Sarah Smith-Jones")], pmap,
        )
        assert "Smith" not in out

    def test_ocr_spacing_variant_still_replaced(self):
        pmap = PseudonymMap(student_name="Sarah Williams")
        out, _ = deidentify_text(
            "Sarah - Williams attended.",
            [match("Sarah Williams")], pmap,
        )
        assert "Williams" not in out

    def test_multiple_people_get_distinct_labels(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        pmap.register_person("Billy Chen")
        matches = [match("Billy Bob"), match("Billy Chen", "Person name (NER)")]
        out, _ = deidentify_text("Billy Bob sat with Billy Chen.", matches, pmap)
        assert out == f"{STUDENT_LABEL} sat with [Person 1]."

    def test_labels_are_not_re_matched(self):
        """A student actually named 'Person' must not corrupt '[Person 1]'."""
        pmap = PseudonymMap(student_name="Person Smith")
        pmap.register_person("Sarah Williams")
        matches = [match("Person"), match("Sarah Williams", "Person name (NER)")]
        out, _ = deidentify_text("Person met Sarah Williams.", matches, pmap)
        assert out == f"{STUDENT_LABEL} met [Person 1]."
        assert "[[" not in out

    def test_deselected_item_is_left_untouched(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        out, count = deidentify_text("Billy Bob and Ann.", [match("Billy Bob")], pmap)
        assert "Ann" in out
        assert count == 1

    def test_no_matches_returns_text_unchanged(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        out, count = deidentify_text("Nothing here.", [], pmap)
        assert out == "Nothing here."
        assert count == 0

    def test_replacement_count_is_accurate(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        out, count = deidentify_text(
            "Billy Bob, Billy, and Billy Bob again.",
            [match("Billy Bob"), match("Billy")], pmap,
        )
        assert count == 3

    def test_organisation_replaced(self):
        pmap = PseudonymMap(student_name="Billy Bob",
                            organisation_names=["Riverside Primary School"])
        out, _ = deidentify_text(
            "Enrolled at Riverside Primary School.",
            [match("Riverside Primary School", "Organisation name")], pmap,
        )
        assert out == "Enrolled at [Organisation 1]."

    def test_very_short_match_is_skipped(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        out, count = deidentify_text("A B C", [match("B")], pmap)
        assert count == 0


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

class TestVerification:

    def test_clean_output_has_no_leftovers(self):
        pmap = PseudonymMap(student_name="Billy Bob")
        out, _ = deidentify_text("Billy Bob is here.", [match("Billy Bob")], pmap)
        assert verify_deidentified(out, ["Billy Bob"], pmap.all_labels()) == []

    def test_deliberate_miss_is_caught(self):
        assert verify_deidentified("Billy Bob is here.", ["Billy Bob"]) == ["Billy Bob"]

    def test_whole_word_check_not_substring(self):
        """'Ann' inside 'Annual' is not a leak."""
        assert verify_deidentified("The annual report.", ["Ann"]) == []

    def test_labels_do_not_trigger_false_leftovers(self):
        pmap = PseudonymMap(student_name="Person Smith")
        out, _ = deidentify_text("Person is here.", [match("Person")], pmap)
        assert verify_deidentified(out, ["Person"], pmap.all_labels()) == []

    def test_strip_labels_only_removes_known_labels(self):
        text = "[Student] and [not a label]"
        stripped = strip_labels(text, {"[Student]"})
        assert "[Student]" not in stripped
        assert "[not a label]" in stripped


class TestFuzzyLeftovers:

    def test_ocr_misread_name_is_caught(self):
        """The OCR text IS the deliverable here — 'Sarnh' must not ship."""
        assert fuzzy_leftovers("Sarnh attended today.", ["Sarah"]) == ["Sarah"]

    def test_clean_output_has_no_fuzzy_leftovers(self):
        assert fuzzy_leftovers("[Student] attended today.", ["Sarah"]) == []

    def test_short_names_are_never_fuzzed(self):
        """'And' must not be flagged for a student named 'Ann'."""
        assert fuzzy_leftovers("And then he left.", ["Ann"]) == []

    def test_non_alphabetic_pii_is_never_fuzzed(self):
        assert fuzzy_leftovers("Call 0412 345 679.", ["0412 345 678"]) == []

    def test_multi_word_name_flags_on_one_token(self):
        assert fuzzy_leftovers("Willianis was present.", ["Sarah Williams"]) == ["Sarah Williams"]

    def test_labels_excluded_from_fuzzy_scan(self):
        pmap = PseudonymMap(student_name="Persan Smith")
        # '[Person 1]' must not fuzzy-match the student's real name 'Persan'.
        out = "[Person 1] was present."
        assert fuzzy_leftovers(out, ["Persan"], pmap.all_labels() | {"[Person 1]"}) == []

    def test_distance_two_allowed_for_long_names(self):
        assert fuzzy_leftovers("Willianis was present.", ["Williams"]) == ["Williams"]
