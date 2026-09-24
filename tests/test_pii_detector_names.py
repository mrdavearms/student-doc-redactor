import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))
from pii_detector import PIIDetector, PIIMatch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _matched_texts(matches):
    """Return the set of .text values from a list of PIIMatch objects."""
    return {m.text for m in matches}


def _categories(matches):
    """Return the set of .category values from a list of PIIMatch objects."""
    return {m.category for m in matches}


def _matches_for_category(matches, category):
    """Filter PIIMatch list to those with a given category."""
    return [m for m in matches if m.category == category]


# ---------------------------------------------------------------------------
# TestNameVariations
# ---------------------------------------------------------------------------

class TestNameVariations:

    def test_full_name_always_present(self):
        detector = PIIDetector("Jane Smith")
        assert "Jane Smith" in detector.name_variations

    def test_first_name_included_for_two_part_name(self):
        detector = PIIDetector("Jane Smith")
        assert "Jane" in detector.name_variations

    def test_last_name_included_for_two_part_name(self):
        detector = PIIDetector("Jane Smith")
        assert "Smith" in detector.name_variations

    def test_initial_dot_last_name_format_included(self):
        # "J. Smith"
        detector = PIIDetector("Jane Smith")
        assert "J. Smith" in detector.name_variations

    def test_first_name_last_initial_format_included(self):
        # "Jane S."
        detector = PIIDetector("Jane Smith")
        assert "Jane S." in detector.name_variations

    def test_dotted_initials_format_included(self):
        # "J.S."
        detector = PIIDetector("Jane Smith")
        assert "J.S." in detector.name_variations

    def test_bare_two_char_initials_not_in_variations(self):
        # "JS" — two characters, must be filtered out as a false-positive risk
        detector = PIIDetector("Jane Smith")
        assert "JS" not in detector.name_variations

    def test_two_char_first_name_is_kept(self):
        # "Jo" is a real name. It used to be dropped by a 3-character minimum,
        # which left it visible in every output for a student called Jo.
        detector = PIIDetector("Jo Nguyen")
        assert "Jo" in detector.name_variations

    def test_two_char_surname_is_kept(self):
        # Li, Wu, Ng, Xu, Vo, Do, Le, Ho are common Australian surnames.
        detector = PIIDetector("Mei Li")
        assert "Li" in detector.name_variations

    def test_two_char_name_matches_as_written_only(self):
        # Two-letter names are matched case-SENSITIVELY so the surname "Do"
        # is never confused with the verb "do", nor "He" with the pronoun.
        detector = PIIDetector("Anh Do")
        texts = [m.text for m in detector.detect_pii_in_text(
            "Do is a quiet student. We do our best. Do you agree?", 1)]
        assert texts.count("Do") == 2
        assert "do" not in texts

    def test_two_char_name_detected_standalone(self):
        detector = PIIDetector("Mei Li")
        texts = [m.text for m in detector.detect_pii_in_text(
            "Li is settled. Mr Li attended. Li's work is neat. LI", 1)]
        assert texts.count("Li") == 3
        assert "LI" not in texts  # all-caps only matches via the full name

    def test_single_letter_parts_are_still_dropped(self):
        detector = PIIDetector("J Smith")
        assert "J" not in detector.name_variations

    def test_short_student_name_itself_preserved(self):
        # Even if student_name is only 2 chars it must be preserved
        detector = PIIDetector("Jo")
        assert "Jo" in detector.name_variations

    def test_single_word_name_no_error(self):
        # A name with no spaces must not crash and must include the name itself
        detector = PIIDetector("Aristotle")
        assert "Aristotle" in detector.name_variations

    def test_single_word_name_no_spurious_variations(self):
        # For a single-word name the code branch for >= 2 parts is skipped,
        # so only the full name (and possibly nothing else) should be present.
        detector = PIIDetector("Aristotle")
        # No variation should be shorter than 2 chars (unless it IS the full name)
        for v in detector.name_variations:
            assert len(v) >= 2 or v == detector.student_name

    def test_three_part_name_first_and_last_included(self):
        # For "Mary Jane Watson", first = "Mary", last = "Watson" should appear
        detector = PIIDetector("Mary Jane Watson")
        assert "Mary" in detector.name_variations
        assert "Watson" in detector.name_variations

    def test_all_variations_meet_minimum_length(self):
        # Every variation must be >= 2 chars OR be the literal student_name
        detector = PIIDetector("Al Smith")
        assert "Al" in detector.name_variations
        for v in detector.name_variations:
            assert len(v) >= 2 or v == detector.student_name, (
                f"Variation {v!r} is shorter than 2 chars and is not the student name"
            )

    def test_variations_are_strings(self):
        detector = PIIDetector("Jane Smith")
        for v in detector.name_variations:
            assert isinstance(v, str)

    def test_leading_trailing_whitespace_stripped_from_student_name(self):
        detector = PIIDetector("  Jane Smith  ")
        assert "Jane Smith" in detector.name_variations
        # The stored student_name should be stripped
        assert detector.student_name == "Jane Smith"


# ---------------------------------------------------------------------------
# TestNameDetection
# ---------------------------------------------------------------------------

class TestNameDetection:

    def test_full_name_detected_in_surrounding_text(self):
        detector = PIIDetector("Jane Smith")
        text = "The student Jane Smith enrolled last year."
        matches = detector.detect_pii_in_text(text, page_num=1)
        name_matches = _matches_for_category(matches, "Student name")
        found_texts = _matched_texts(name_matches)
        # "Jane Smith" OR "Jane" and "Smith" individually — full name must be present
        assert any("Jane Smith" in t for t in found_texts) or (
            "Jane" in found_texts and "Smith" in found_texts
        )

    def test_detection_is_case_insensitive(self):
        detector = PIIDetector("Jane Smith")
        text = "JANE SMITH is listed here."
        matches = detector.detect_pii_in_text(text, page_num=1)
        name_matches = _matches_for_category(matches, "Student name")
        assert len(name_matches) > 0, "Should detect name case-insensitively"

    def test_word_boundary_prevents_partial_match(self):
        # "Jane Bloggs" — "Bloggsel" must NOT trigger a match for "Bloggs"
        detector = PIIDetector("Jane Bloggs")
        text = "Please refer to the bloggsel herb recipe."
        matches = detector.detect_pii_in_text(text, page_num=1)
        name_matches = _matches_for_category(matches, "Student name")
        # "Bloggs" must not appear in matched texts when only "bloggsel" is in the line
        for m in name_matches:
            assert m.text.lower() != "bloggs", (
                "Word boundary check failed: 'bloggs' matched inside 'bloggsel'"
            )

    def test_first_name_alone_detected(self):
        detector = PIIDetector("Jane Smith")
        text = "Jane attended the session."
        matches = detector.detect_pii_in_text(text, page_num=1)
        name_matches = _matches_for_category(matches, "Student name")
        found_texts = {m.text.lower() for m in name_matches}
        assert "jane" in found_texts

    def test_last_name_alone_detected(self):
        detector = PIIDetector("Jane Smith")
        text = "The report for Smith has been filed."
        matches = detector.detect_pii_in_text(text, page_num=1)
        name_matches = _matches_for_category(matches, "Student name")
        found_texts = {m.text.lower() for m in name_matches}
        assert "smith" in found_texts

    def test_no_matches_for_name_not_in_text(self):
        detector = PIIDetector("Jane Smith")
        text = "The quick brown fox jumps over the lazy dog."
        matches = detector.detect_pii_in_text(text, page_num=1)
        name_matches = _matches_for_category(matches, "Student name")
        assert len(name_matches) == 0

    def test_match_carries_correct_page_number(self):
        detector = PIIDetector("Jane Smith")
        text = "Jane Smith"
        matches = detector.detect_pii_in_text(text, page_num=7)
        name_matches = _matches_for_category(matches, "Student name")
        assert len(name_matches) > 0
        for m in name_matches:
            assert m.page_num == 7

    def test_match_carries_correct_line_number(self):
        detector = PIIDetector("Jane Smith")
        text = "First line\nSecond line\nJane Smith appears here"
        matches = detector.detect_pii_in_text(text, page_num=1)
        name_matches = _matches_for_category(matches, "Student name")
        assert len(name_matches) > 0
        for m in name_matches:
            assert m.line_num == 3

    def test_match_confidence_is_high_for_name(self):
        detector = PIIDetector("Jane Smith")
        text = "Jane Smith"
        matches = detector.detect_pii_in_text(text, page_num=1)
        name_matches = _matches_for_category(matches, "Student name")
        assert len(name_matches) > 0
        for m in name_matches:
            assert m.confidence >= 0.8

    def test_dotted_initial_format_detected(self):
        # "J. Smith" should be detected when present in text
        detector = PIIDetector("Jane Smith")
        text = "Signed off by J. Smith today."
        matches = detector.detect_pii_in_text(text, page_num=1)
        name_matches = _matches_for_category(matches, "Student name")
        found_texts = {m.text for m in name_matches}
        assert "J. Smith" in found_texts

    def test_multiple_occurrences_all_detected(self):
        detector = PIIDetector("Jane Smith")
        text = "Jane Smith was listed. Later, Jane Smith appeared again."
        matches = detector.detect_pii_in_text(text, page_num=1)
        name_matches = _matches_for_category(matches, "Student name")
        full_name_hits = [m for m in name_matches if m.text.lower() == "jane smith"]
        assert len(full_name_hits) >= 2

    def test_name_across_multiple_lines_each_detected(self):
        detector = PIIDetector("Jane Smith")
        text = "Jane Smith\nSome other text\nJane Smith again"
        matches = detector.detect_pii_in_text(text, page_num=1)
        name_matches = _matches_for_category(matches, "Student name")
        line_numbers = {m.line_num for m in name_matches}
        assert 1 in line_numbers
        assert 3 in line_numbers

    def test_two_char_initials_not_detected_as_name(self):
        # "JS" was a false-positive bug; it must not appear as a variation
        detector = PIIDetector("Jane Smith")
        text = "The JS library is widely used."
        matches = detector.detect_pii_in_text(text, page_num=1)
        name_matches = _matches_for_category(matches, "Student name")
        for m in name_matches:
            assert m.text != "JS", "Two-char bare initials must not be flagged as a name"


# ---------------------------------------------------------------------------
# TestContextualNameDetection
# ---------------------------------------------------------------------------

class TestContextualNameDetection:

    def test_mother_keyword_detects_parent_guardian(self):
        detector = PIIDetector("Tom Jones")
        text = "Mother: Jane Smith"
        matches = detector.detect_pii_in_text(text, page_num=1)
        contextual = _matches_for_category(matches, "Parent/Guardian")
        assert len(contextual) > 0
        found_texts = _matched_texts(contextual)
        assert any("Jane" in t or "Jane Smith" in t for t in found_texts)

    def test_father_keyword_detects_parent_guardian(self):
        detector = PIIDetector("Tom Jones")
        text = "Father: Bob Jones"
        matches = detector.detect_pii_in_text(text, page_num=1)
        contextual = _matches_for_category(matches, "Parent/Guardian")
        assert len(contextual) > 0
        found_texts = _matched_texts(contextual)
        assert any("Bob" in t for t in found_texts)

    def test_emergency_contact_detects_family_member(self):
        detector = PIIDetector("Tom Jones")
        text = "Emergency Contact: Mary Brown"
        matches = detector.detect_pii_in_text(text, page_num=1)
        family_matches = _matches_for_category(matches, "Family member")
        assert len(family_matches) > 0
        found_texts = _matched_texts(family_matches)
        assert any("Mary" in t for t in found_texts)

    def test_brother_keyword_detects_family_member(self):
        detector = PIIDetector("Tom Jones")
        text = "Brother: Tom Green"
        matches = detector.detect_pii_in_text(text, page_num=1)
        family_matches = _matches_for_category(matches, "Family member")
        assert len(family_matches) > 0
        found_texts = _matched_texts(family_matches)
        assert any("Tom" in t for t in found_texts)

    def test_title_word_after_guardian_not_flagged_as_name(self):
        # "Guardian: Mr Williams" — "Mr" is a title and should be skipped;
        # "Williams" however should still be caught.
        detector = PIIDetector("Tom Jones")
        text = "Guardian: Mr Williams"
        matches = detector.detect_pii_in_text(text, page_num=1)
        contextual = [m for m in matches if m.category in ("Parent/Guardian", "Family member")]
        found_texts = _matched_texts(contextual)
        # "Mr" must not appear as a standalone detected name
        assert "Mr" not in found_texts, "Title 'Mr' should not be flagged as a detected name"

    def test_user_provided_parent_name_detected_with_high_confidence(self):
        detector = PIIDetector("Tom Jones", parent_names=["Sandra Jones"])
        text = "Signed by Sandra Jones on the form."
        matches = detector.detect_pii_in_text(text, page_num=1)
        parent_matches = _matches_for_category(matches, "Parent/Guardian (user-provided)")
        assert len(parent_matches) > 0
        for m in parent_matches:
            assert m.confidence >= 0.8

    def test_user_provided_parent_name_case_insensitive(self):
        detector = PIIDetector("Tom Jones", parent_names=["Sandra Jones"])
        text = "SANDRA JONES gave permission."
        matches = detector.detect_pii_in_text(text, page_num=1)
        parent_matches = _matches_for_category(matches, "Parent/Guardian (user-provided)")
        assert len(parent_matches) > 0

    def test_user_provided_family_name_detected_with_high_confidence(self):
        detector = PIIDetector("Tom Jones", family_names=["Uncle Dave"])
        text = "Uncle Dave picked Tom up from school."
        matches = detector.detect_pii_in_text(text, page_num=1)
        family_matches = _matches_for_category(matches, "Family member (user-provided)")
        assert len(family_matches) > 0
        for m in family_matches:
            assert m.confidence >= 0.8

    def test_keyword_without_following_name_does_not_crash(self):
        # A line that ends with the keyword and no name after it must not raise
        detector = PIIDetector("Tom Jones")
        text = "Please contact the Mother"
        try:
            matches = detector.detect_pii_in_text(text, page_num=1)
        except Exception as exc:
            assert False, f"detect_pii_in_text raised an exception: {exc}"

    def test_carer_keyword_categorised_as_parent_guardian(self):
        detector = PIIDetector("Tom Jones")
        text = "Carer: Helen Ford"
        matches = detector.detect_pii_in_text(text, page_num=1)
        carer_matches = _matches_for_category(matches, "Parent/Guardian")
        assert len(carer_matches) > 0

    def test_sister_keyword_categorised_as_family_member(self):
        detector = PIIDetector("Tom Jones")
        text = "Sister: Alice Jones"
        matches = detector.detect_pii_in_text(text, page_num=1)
        family_matches = _matches_for_category(matches, "Family member")
        assert len(family_matches) > 0

    def test_next_of_kin_keyword_categorised_as_family_member(self):
        detector = PIIDetector("Tom Jones")
        text = "Next of Kin: Carol White"
        matches = detector.detect_pii_in_text(text, page_num=1)
        family_matches = _matches_for_category(matches, "Family member")
        assert len(family_matches) > 0

    def test_mum_keyword_categorised_as_parent_guardian(self):
        detector = PIIDetector("Tom Jones")
        text = "Mum: Patricia Jones"
        matches = detector.detect_pii_in_text(text, page_num=1)
        parent_matches = _matches_for_category(matches, "Parent/Guardian")
        assert len(parent_matches) > 0

    def test_contextual_match_has_medium_confidence(self):
        detector = PIIDetector("Tom Jones")
        text = "Father: Bob Jones"
        matches = detector.detect_pii_in_text(text, page_num=1)
        parent_matches = _matches_for_category(matches, "Parent/Guardian")
        assert len(parent_matches) > 0
        for m in parent_matches:
            assert 0.5 <= m.confidence < 0.8

    def test_user_provided_parent_name_not_in_text_produces_no_match(self):
        detector = PIIDetector("Tom Jones", parent_names=["Sandra Jones"])
        text = "No relevant names in this sentence."
        matches = detector.detect_pii_in_text(text, page_num=1)
        parent_matches = _matches_for_category(matches, "Parent/Guardian (user-provided)")
        assert len(parent_matches) == 0

    def test_multiple_parent_names_all_detected(self):
        detector = PIIDetector("Tom Jones", parent_names=["Sandra Jones", "Bob Jones"])
        text = "Sandra Jones and Bob Jones attended the meeting."
        matches = detector.detect_pii_in_text(text, page_num=1)
        parent_matches = _matches_for_category(matches, "Parent/Guardian (user-provided)")
        found_texts = _matched_texts(parent_matches)
        assert any("Sandra" in t for t in found_texts)
        assert any("Bob" in t for t in found_texts)

    def test_lowercase_word_after_keyword_not_captured(self):
        """'Parent email:' must not flag the word 'email' as a name."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text(
            "Parent email: nick.williams@gmail.com", page_num=1)
        contextual = [m for m in matches
                      if m.category in ("Parent/Guardian", "Family member")]
        assert not any(m.text == "email" for m in contextual)

    def test_lowercase_phrase_after_keyword_not_captured(self):
        """Today this captures 'reports that'; after the fix, nothing."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text(
            "Mother reports that homework is difficult", page_num=1)
        contextual = [m for m in matches
                      if m.category in ("Parent/Guardian", "Family member")]
        assert not contextual, f"Unexpected contextual matches: {[m.text for m in contextual]}"

    def test_allcaps_name_after_keyword_still_captured(self):
        """ALL-CAPS names (form headers) must still be captured."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("MOTHER: JANE attended", page_num=1)
        contextual = [m for m in matches if m.category == "Parent/Guardian"]
        assert any("JANE" in m.text for m in contextual)


# ---------------------------------------------------------------------------
# Contextual Name Exclude List Tests
# ---------------------------------------------------------------------------

class TestContextualNameExcludeList:

    def test_dad_after_carer_not_extracted_as_name(self):
        """'Dad' after a keyword is a relationship word, not a person name."""
        detector = PIIDetector("Jane Smith")
        matches = detector.detect_pii_in_text("Carer: Dad", page_num=1)
        contextual = [m for m in matches if m.category in ("Parent/Guardian", "Family member")]
        flagged_texts = [m.text for m in contextual]
        assert "Dad" not in flagged_texts, f"'Dad' should not be extracted as a name, got: {flagged_texts}"

    def test_mum_after_carer_not_extracted_as_name(self):
        detector = PIIDetector("Jane Smith")
        matches = detector.detect_pii_in_text("Carer: Mum", page_num=1)
        contextual = [m for m in matches if m.category in ("Parent/Guardian", "Family member")]
        assert not any(m.text in ("Mum", "Mom") for m in contextual)

    def test_mother_after_lives_with_not_extracted(self):
        detector = PIIDetector("Jane Smith")
        matches = detector.detect_pii_in_text("Lives with Mother and siblings.", page_num=1)
        contextual = [m for m in matches if m.category in ("Parent/Guardian", "Family member")]
        assert not any(m.text == "Mother" for m in contextual)

    def test_real_name_after_carer_still_extracted(self):
        """A real name after 'Carer:' must still be captured."""
        detector = PIIDetector("Jane Smith")
        matches = detector.detect_pii_in_text("Carer: Sarah Thompson", page_num=1)
        contextual = [m for m in matches if m.category in ("Parent/Guardian", "Family member")]
        assert any("Sarah" in m.text or "Thompson" in m.text for m in contextual), \
            "Real name after 'Carer:' should be extracted"


# ---------------------------------------------------------------------------
# Parenthetical and Comma-Separated Contextual Name Tests
# ---------------------------------------------------------------------------

class TestContextualNameParenthetical:
    """Names after family keywords in parentheses or after commas."""

    def test_father_name_in_parentheses(self):
        """'his father (Nick)' should detect 'Nick' as Parent/Guardian."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("his father (Nick) reported the behaviour", page_num=1)
        contextual = [m for m in matches if m.category in ("Parent/Guardian", "Family member")]
        found_texts = [m.text for m in contextual]
        assert any("Nick" in t for t in found_texts), f"Expected 'Nick' in {found_texts}"

    def test_sister_name_after_comma(self):
        """'his sister, Summer,' should detect 'Summer' as Family member."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("his sister, Summer, was also present", page_num=1)
        contextual = [m for m in matches if m.category in ("Parent/Guardian", "Family member")]
        found_texts = [m.text for m in contextual]
        assert any("Summer" in t for t in found_texts), f"Expected 'Summer' in {found_texts}"

    def test_mother_name_in_parentheses(self):
        """'Mother (Jane Smith)' should detect 'Jane Smith'."""
        detector = PIIDetector("Tom Jones")
        matches = detector.detect_pii_in_text("Mother (Jane Smith) was contacted", page_num=1)
        contextual = [m for m in matches if m.category in ("Parent/Guardian", "Family member")]
        found_texts = [m.text for m in contextual]
        assert any("Jane" in t for t in found_texts), f"Expected 'Jane' in {found_texts}"

    def test_partner_keyword_in_parentheses(self):
        """'his partner (Steph)' — 'partner' is not currently a keyword but should be
        handled if added. For now this tests the parenthetical pattern with existing keywords."""
        # Using 'Carer' as it's an existing keyword
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("Carer (Steph) visited the school", page_num=1)
        contextual = [m for m in matches if m.category in ("Parent/Guardian", "Family member")]
        found_texts = [m.text for m in contextual]
        assert any("Steph" in t for t in found_texts), f"Expected 'Steph' in {found_texts}"

    def test_pronoun_father_parenthetical_pattern(self):
        """'his father (Nick)' with pronoun prefix should detect name."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("Joe lives with his father (Nick) and sister", page_num=1)
        contextual = [m for m in matches if m.category in ("Parent/Guardian", "Family member")]
        found_texts = [m.text for m in contextual]
        assert any("Nick" in t for t in found_texts), f"Expected 'Nick' in {found_texts}"

    def test_parenthetical_excludes_relationship_words(self):
        """'Father (Dad)' — 'Dad' is a relationship word, not a name."""
        detector = PIIDetector("Joe Bloggs")
        matches = detector.detect_pii_in_text("Father (Dad) was present", page_num=1)
        contextual = [m for m in matches if m.category in ("Parent/Guardian", "Family member")]
        found_texts = [m.text for m in contextual]
        assert "Dad" not in found_texts, f"'Dad' should not be flagged as name, got {found_texts}"


# ---------------------------------------------------------------------------
# TestOrganisationNameDetection
# ---------------------------------------------------------------------------

class TestOrganisationNameDetection:
    """Organisation names provided by the user should be detected as PII."""

    def test_full_org_name_detected(self):
        detector = PIIDetector("Jane Smith", organisation_names=["Greenwood Primary School"])
        matches = detector.detect_pii_in_text("Report prepared by Greenwood Primary School", 1)
        org_matches = [m for m in matches if m.category == 'Organisation name']
        assert len(org_matches) >= 1
        assert any("Greenwood Primary School" in m.text for m in org_matches)

    def test_org_name_individual_words_detected(self):
        """Individual significant words from org name should also match."""
        detector = PIIDetector("Jane Smith", organisation_names=["Greenwood Primary School"])
        matches = detector.detect_pii_in_text("The Greenwood campus is located nearby", 1)
        org_matches = [m for m in matches if m.category == 'Organisation name']
        assert len(org_matches) >= 1

    def test_org_name_short_words_excluded(self):
        """Words shorter than 3 chars from org names should not become variations."""
        detector = PIIDetector("Jane Smith", organisation_names=["St Mary's"])
        # "St" is only 2 chars — should not match standalone
        matches = detector.detect_pii_in_text("St Patrick went to the store", 1)
        org_matches = [m for m in matches if m.category == 'Organisation name']
        # Should NOT match "St" alone — only full "St Mary's" or "Mary's" (5 chars)
        assert not any(m.text == "St" for m in org_matches)

    def test_org_name_confidence_is_095(self):
        detector = PIIDetector("Jane Smith", organisation_names=["Riverside Clinic"])
        matches = detector.detect_pii_in_text("Riverside Clinic assessment results", 1)
        org_matches = [m for m in matches if m.category == 'Organisation name']
        assert len(org_matches) >= 1
        assert org_matches[0].confidence == 0.95

    def test_multiple_org_names(self):
        detector = PIIDetector("Jane Smith", organisation_names=["Greenwood PS", "Dr Kim Psychology"])
        matches = detector.detect_pii_in_text("Referred by Dr Kim Psychology to Greenwood PS", 1)
        org_matches = [m for m in matches if m.category == 'Organisation name']
        assert len(org_matches) >= 2

    def test_org_name_none_defaults_to_empty(self):
        """Passing None for organisation_names should not crash."""
        detector = PIIDetector("Jane Smith", organisation_names=None)
        assert detector.organisation_names == []

    def test_org_name_source_is_regex(self):
        detector = PIIDetector("Jane Smith", organisation_names=["Riverside Clinic"])
        matches = detector.detect_pii_in_text("Riverside Clinic report", 1)
        org_matches = [m for m in matches if m.category == 'Organisation name']
        assert all(m.source == 'regex' for m in org_matches)


class TestNicknameExpansion:
    def test_christopher_expands_to_chris(self):
        detector = PIIDetector("Christopher Brown")
        text = "Chris was late to class"
        matches = detector.detect_pii_in_text(text, 1)
        assert any(m.text.lower() == "chris" for m in matches)

    def test_chris_expands_to_christopher(self):
        detector = PIIDetector("Chris Brown")
        text = "Christopher was late to class"
        matches = detector.detect_pii_in_text(text, 1)
        assert any("christopher" in m.text.lower() for m in matches)

    def test_nickname_confidence_is_075(self):
        detector = PIIDetector("Christopher Brown")
        text = "Chris was late"
        matches = [m for m in detector.detect_pii_in_text(text, 1) if m.text.lower() == "chris"]
        assert len(matches) >= 1
        assert matches[0].confidence == 0.75

    def test_short_nickname_excluded_if_in_contextual_exclude(self):
        # "Art" is a common word — should be excluded
        detector = PIIDetector("Arthur Jones")
        text = "The Art program runs weekly"
        matches = [m for m in detector.detect_pii_in_text(text, 1) if m.text.lower() == "art"]
        assert len(matches) == 0


from pii_detector import generate_name_variations


class TestNamesAsTheyAreActuallyWritten:
    """Variations for the ways names really appear in reports."""

    def test_initials_forms_match_in_text(self):
        # "Jane S." and "J.S." end in a full stop, which \b could not follow;
        # they only ever matched when glued to the next word.
        detector = PIIDetector("Jane Smith")
        texts = [m.text for m in detector.detect_pii_in_text(
            "Report for Jane S. from Term 2. Student J.S. was seen. Student: J.S.", 1)]
        assert "Jane S." in texts
        assert texts.count("J.S.") == 2

    def test_hyphenated_surname_halves_are_variations(self):
        detector = PIIDetector("Sarah Smith-Jones")
        assert "Smith" in detector.name_variations
        assert "Jones" in detector.name_variations
        texts = [m.text for m in detector.detect_pii_in_text(
            "Sarah Smith was seen. The Jones family attended.", 1)]
        assert "Smith" in texts and "Jones" in texts

    def test_surname_particles_are_part_of_the_surname(self):
        variations = generate_name_variations("Jan van der Berg")[0]
        assert "van der Berg" in variations
        assert "Berg" in variations

    def test_class_list_order_is_understood(self):
        variations = generate_name_variations("Smith, John")[0]
        assert "John Smith" in variations
        assert "Smith" in variations
        assert "Smith," not in variations

    def test_middle_name_is_dropped_in_running_text(self):
        # "Billy Robert Bob" is written "Billy Bob" in the body of a report.
        variations = generate_name_variations("Billy Robert Bob")[0]
        assert "Billy Bob" in variations

    def test_leading_title_is_not_part_of_the_name(self):
        variations = generate_name_variations("Mr John Bob")[0]
        assert "John Bob" in variations
        assert "John" in variations
        assert "Mr" not in variations

    def test_a_lone_initial_is_not_a_variation(self):
        variations = generate_name_variations("P. Raman")[0]
        assert "P." not in variations
        assert "Raman" in variations

    def test_parent_first_name_alone_is_found(self):
        detector = PIIDetector("Billy Bob", parent_names=["Mr John Chen"])
        texts = [m.text for m in detector.detect_pii_in_text(
            "John Chen attended. John said so. Mr John Chen signed.", 1)]
        assert texts.count("John Chen") == 2
        assert "John" in texts

    def test_curly_apostrophe_in_the_entered_name_still_matches(self):
        # A name pasted from Word carries U+2019; the page text is normalised
        # to a straight quote before matching, so the name must be as well.
        detector = PIIDetector("Siobhan O\u2019Brien")
        texts = [m.text for m in detector.detect_pii_in_text(
            "Siobhan O\u2019Brien reads well. O'Brien too.", 1)]
        assert texts.count("O'Brien") == 2

    def test_parent_event_phrases_are_not_parents(self):
        detector = PIIDetector("Billy Bob")
        matches = detector.detect_pii_in_text(
            "Parent Teacher Interview held in Term 2. Parent Information Evening attended. "
            "Parent: Sarah Jones.", 1)
        contextual = [m.text for m in matches if m.category == 'Parent/Guardian']
        assert contextual == ["Sarah Jones"]

    def test_calendar_abbreviations_are_not_nicknames(self):
        detector = PIIDetector("Declan Murphy")
        matches = detector.detect_pii_in_text("Assessed Dec 2024. Review due Mon.", 1)
        assert not [m for m in matches if m.category == 'Student name (nickname)']

    def test_relationship_words_typed_into_the_family_box_are_not_names(self):
        detector = PIIDetector("Billy Bob", family_names=["The Smith family", "Nan Jean"])
        texts = [m.text for m in detector.detect_pii_in_text(
            "The class met the family. Nan Jean and Jean came. Smith too.", 1)]
        assert "The" not in texts and "the" not in texts and "family" not in texts
        assert "Nan" not in texts
        assert "Jean" in texts and "Smith" in texts

    def test_common_first_name_of_a_parent_is_still_found(self):
        detector = PIIDetector("Billy Bob", parent_names=["Bob Smith"])
        texts = [m.text for m in detector.detect_pii_in_text("Bob came in.", 1)]
        assert "Bob" in texts
