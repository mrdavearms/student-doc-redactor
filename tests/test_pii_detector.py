import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))
from pii_detector import PIIDetector, PIIMatch


class TestPhoneDetection:
    def setup_method(self):
        self.detector = PIIDetector("Jane Smith")

    def _phone_matches(self, line):
        return self.detector._detect_phones(line, 1, 1)

    def test_mobile_with_spaces_detected(self):
        matches = self._phone_matches("Call me on 0412 345 678 please")
        assert len(matches) == 1
        assert matches[0].category == 'Phone number'
        assert '0412 345 678' in matches[0].text

    def test_mobile_no_spaces_detected(self):
        # 0412345678 is matched by multiple overlapping phone patterns (04\d{8},
        # 04\d{2}\s*\d{3}\s*\d{3}, and 0[2-478]\s*\d{4}\s*\d{4}) — all correct
        matches = self._phone_matches("My mobile is 0412345678")
        assert len(matches) >= 1
        assert all(m.category == 'Phone number' for m in matches)
        assert any('0412345678' in m.text for m in matches)

    def test_landline_detected(self):
        matches = self._phone_matches("Phone: 02 9876 5432")
        assert len(matches) == 1
        assert matches[0].category == 'Phone number'

    def test_landline_with_parentheses_detected(self):
        matches = self._phone_matches("Call (02) 9876 5432 during business hours")
        assert len(matches) == 1
        assert matches[0].category == 'Phone number'

    def test_international_format_detected(self):
        matches = self._phone_matches("International: +61 2 9876 5432")
        assert len(matches) == 1
        assert matches[0].category == 'Phone number'

    def test_random_10_digit_number_not_detected(self):
        matches = self._phone_matches("Reference number: 1234567890")
        assert len(matches) == 0

    def test_mobile_with_dashes_detected(self):
        matches = self._phone_matches("Call 0412-345-678 for pickup")
        assert len(matches) >= 1

    def test_mobile_international_format_spaced(self):
        """'+61 412 345 678' — the standard intl mobile format."""
        matches = self._phone_matches("Contact: +61 412 345 678")
        phones = [m for m in matches if m.category == "Phone number"]
        assert any("412 345 678" in m.text for m in phones)

    def test_landline_dotted_separators(self):
        """'02.6056.1234' — dot-separated landline."""
        matches = self._phone_matches("Ph: 02.6056.1234")
        phones = [m for m in matches if m.category == "Phone number"]
        assert any("6056" in m.text for m in phones)

    def test_mobile_dotted_separators(self):
        """'0412.345.678' — dot-separated mobile."""
        matches = self._phone_matches("Mob: 0412.345.678")
        phones = [m for m in matches if m.category == "Phone number"]
        assert len(phones) >= 1

    def test_dotted_pattern_does_not_match_inside_a_longer_digit_run(self):
        """Version/score strings must not become phone numbers."""
        matches = self._phone_matches("Version 2.04.1234.5678 build")
        phones = [m for m in matches if m.category == "Phone number"]
        assert len(phones) == 0


class TestEmailDetection:
    def setup_method(self):
        self.detector = PIIDetector("Jane Smith")

    def _email_matches(self, line):
        return self.detector._detect_emails(line, 1, 1)

    def test_simple_email_detected(self):
        matches = self._email_matches("Contact user@example.com for details")
        assert len(matches) == 1
        assert matches[0].category == 'Email address'
        assert matches[0].text == 'user@example.com'

    def test_email_with_dots_and_plus_detected(self):
        matches = self._email_matches("Email: jane.doe+tag@school.edu.au")
        assert len(matches) == 1
        assert matches[0].text == 'jane.doe+tag@school.edu.au'

    def test_plain_text_without_at_not_detected(self):
        matches = self._email_matches("This text has no email at all")
        assert len(matches) == 0


class TestAddressDetection:
    def setup_method(self):
        self.detector = PIIDetector("Jane Smith")

    def _address_matches(self, line):
        return self.detector._detect_addresses(line, 1, 1)

    def test_full_address_vic_detected(self):
        matches = self._address_matches("Address: 12 Oak Street, Melbourne, VIC 3000")
        assert len(matches) == 1
        assert matches[0].category == 'Address'

    def test_address_nsw_detected(self):
        matches = self._address_matches("Lives at 45 George Street, Sydney, NSW 2000")
        assert len(matches) == 1
        assert matches[0].category == 'Address'

    def test_address_abbreviated_street_type_detected(self):
        matches = self._address_matches("7 Elm Rd, Brunswick, VIC 3056")
        assert len(matches) == 1

    def test_text_without_state_not_matched(self):
        matches = self._address_matches("123 Some Place without any proper suburb here")
        assert len(matches) == 0

    def test_address_close_detected(self):
        matches = self._address_matches("Lives at 5 Rosemary Close, Richmond VIC 3121")
        assert len(matches) >= 1

    def test_address_circuit_detected(self):
        matches = self._address_matches("Address: 12 Sunset Circuit, Cairns QLD 4870")
        assert len(matches) >= 1

    def test_address_with_unit_prefix(self):
        matches = self._address_matches("Address: Unit 3/45 High Street, Wodonga VIC 3690")
        addr = [m for m in matches if m.category == "Address"]
        assert any(m.text.startswith("Unit 3/45") for m in addr)

    def test_address_with_bare_unit_slash_prefix(self):
        matches = self._address_matches("Lives at 3/45 High Street, Wodonga VIC 3690")
        addr = [m for m in matches if m.category == "Address"]
        assert any(m.text.startswith("3/45") for m in addr)

    def test_street_only_address_in_prose(self):
        """Addresses without state+postcode get a medium-confidence match."""
        matches = self._address_matches("Sarah lives at 12 Bakers Lane with her mother.")
        addr = [m for m in matches if m.category == "Address"]
        assert any(m.text == "12 Bakers Lane" for m in addr)
        assert all(m.confidence == 0.65 for m in addr)

    def test_street_only_ambiguous_type_requires_terminator(self):
        """'5 Rosewood Court,' is an address; '2 Year Level Place Value' is not."""
        hit = self._address_matches("The family moved to 5 Rosewood Court, Wodonga")
        assert any(m.category == "Address" and m.text == "5 Rosewood Court" for m in hit)

        miss = self._address_matches("Working at 2 Year Level Place Value")
        assert not [m for m in miss if m.category == "Address"]

    def test_street_only_keeps_the_esplanade_style_names(self):
        matches = self._address_matches("Lives at 12 The Esplanade, Torquay")
        addr = [m for m in matches if m.category == "Address"]
        assert any(m.text == "12 The Esplanade" for m in addr)

    def test_full_address_not_double_reported(self):
        """A full-format address must yield ONE match, not full + street-only."""
        matches = self._address_matches("Address: 12 Bakers Lane, Wodonga VIC 3690")
        addr = [m for m in matches if m.category == "Address"]
        assert len(addr) == 1
        assert addr[0].confidence == 0.95


class TestMedicareDetection:
    def setup_method(self):
        self.detector = PIIDetector("Jane Smith")

    def _medicare_matches(self, line):
        return self.detector._detect_medicare(line, 1, 1)

    def test_number_alone_no_keyword_zero_matches(self):
        matches = self._medicare_matches("2123 45678 1")
        assert len(matches) == 0

    def test_with_medicare_keyword_one_match(self):
        matches = self._medicare_matches("Medicare: 2123 45678 1")
        assert len(matches) == 1
        assert matches[0].category == 'Medicare number'

    def test_no_spaces_with_keyword_matches(self):
        matches = self._medicare_matches("Medicare number is 2123456781")
        assert len(matches) == 1
        assert matches[0].category == 'Medicare number'

    def test_wrong_grouping_no_match(self):
        # 3+5+2 grouping: "212 34567 81" — the leading group has only 3 digits so
        # \b\d{4} cannot match at a word boundary before "212"; no match expected.
        matches = self._medicare_matches("My medicare card number is 212 34567 81")
        assert len(matches) == 0

    def test_11_digit_number_with_keyword_no_match(self):
        # 11 digits — word boundary prevents match because it runs into more digits
        matches = self._medicare_matches("medicare 21234567810")
        assert len(matches) == 0

    def test_9_digit_number_with_keyword_no_match(self):
        matches = self._medicare_matches("medicare 212345678")
        assert len(matches) == 0


class TestCRNDetection:
    def setup_method(self):
        self.detector = PIIDetector("Jane Smith")

    def _crn_matches(self, line):
        return self.detector._detect_crn(line, 1, 1)

    def test_crn_label_with_9_char_token_matches(self):
        matches = self._crn_matches("CRN: ABC123456")
        assert len(matches) == 1
        assert matches[0].category == 'Centrelink CRN'
        assert matches[0].text == 'ABC123456'

    def test_9_char_token_alone_no_crn_no_match(self):
        matches = self._crn_matches("ABC123456")
        assert len(matches) == 0

    def test_crn_label_but_no_9_char_token_no_match(self):
        matches = self._crn_matches("CRN: AB12")
        assert len(matches) == 0

    def test_crn_real_format_spaced(self):
        """Real CRNs are 9 digits + a letter: '123 456 789A'."""
        matches = self._crn_matches("CRN: 123 456 789A")
        assert len(matches) == 1
        assert matches[0].text == "123 456 789A"

    def test_crn_real_format_compact(self):
        """Compact real CRN: '123456789A' (10 chars, digit run + letter)."""
        matches = self._crn_matches("CRN: 123456789A")
        assert len(matches) == 1
        assert matches[0].text == "123456789A"

    def test_crn_letter_format_requires_keyword(self):
        """Without a CRN keyword on the line, the number is not flagged."""
        matches = self._crn_matches("Reference 123 456 789A")
        assert len(matches) == 0


class TestStudentIDDetection:
    def setup_method(self):
        self.detector = PIIDetector("Jane Bloggs")

    def _student_id_matches(self, line):
        return self.detector._detect_student_id(line, 1, 1)

    def test_3_letters_3_digits_matches(self):
        matches = self._student_id_matches("Student ID: FEN123")
        assert len(matches) == 1
        assert matches[0].category == 'Student ID'

    def test_3_letters_4_digits_matches(self):
        matches = self._student_id_matches("ID: FEN1234")
        assert len(matches) == 1

    def test_3_letters_2_digits_no_match(self):
        matches = self._student_id_matches("Code: FEN12")
        assert len(matches) == 0

    def test_3_letters_1_digit_no_match(self):
        matches = self._student_id_matches("Code: FEN1")
        assert len(matches) == 0

    def test_nsw1_no_match(self):
        # NSW1 is only 1 digit — does not satisfy \d{3,}
        matches = self._student_id_matches("State: NSW1")
        assert len(matches) == 0

    def test_surname_prefix_match_gives_high_confidence(self):
        # Student is "Jane Bloggs", surname prefix = "BLO"
        matches = self._student_id_matches("BLO1234")
        assert len(matches) == 1
        assert matches[0].confidence >= 0.8

    def test_non_matching_prefix_gives_medium_confidence(self):
        matches = self._student_id_matches("ZZZ9999")
        assert len(matches) == 1
        assert 0.5 <= matches[0].confidence < 0.8


class TestDOBDetection:
    def setup_method(self):
        self.detector = PIIDetector("Jane Smith")

    def _dob_matches(self, line):
        return self.detector._detect_dob(line, 1, 1)

    def test_dob_slash_format_detected(self):
        matches = self._dob_matches("DOB: 15/03/2010")
        assert len(matches) == 1
        assert matches[0].category == 'Date of birth'
        assert matches[0].text == '15/03/2010'

    def test_date_of_birth_dash_format_detected(self):
        matches = self._dob_matches("Date of Birth: 15-03-2010")
        assert len(matches) == 1
        assert matches[0].text == '15-03-2010'

    def test_born_long_month_format_detected(self):
        matches = self._dob_matches("Born: 15 March 2010")
        assert len(matches) == 1
        assert matches[0].text == '15 March 2010'

    def test_dob_dot_abbreviation_detected(self):
        matches = self._dob_matches("D.O.B.: 15/03/2010")
        assert len(matches) == 1

    def test_date_alone_without_label_no_match(self):
        matches = self._dob_matches("15/03/2010")
        assert len(matches) == 0

    def test_date_of_birth_lowercase_label_detected(self):
        matches = self._dob_matches("Date of birth: 15 Jan 2010")
        assert len(matches) == 1
        assert matches[0].category == 'Date of birth'

    def test_dob_dotted_separators(self):
        matches = self._dob_matches("DOB: 12.03.2015")
        assert len(matches) == 1
        assert matches[0].text == "12.03.2015"

    def test_dob_two_digit_year(self):
        matches = self._dob_matches("DOB: 12/3/15")
        assert len(matches) == 1
        assert matches[0].text == "12/3/15"

    def test_dob_ordinal_day(self):
        matches = self._dob_matches("Date of Birth: 12th March 2015")
        assert len(matches) == 1
        assert matches[0].text == "12th March 2015"

    def test_dob_ordinal_with_of(self):
        matches = self._dob_matches("Born: 3rd of June 2014")
        assert len(matches) == 1
        assert matches[0].text == "3rd of June 2014"

    def test_dob_month_first_us_style(self):
        matches = self._dob_matches("Born: March 12, 2015")
        assert len(matches) == 1
        assert matches[0].text == "March 12, 2015"

    def test_standalone_dotted_date_without_label_not_flagged(self):
        """Dotted dates still require a DOB label — review dates stay unflagged."""
        matches = self._dob_matches("Review meeting held 12.03.2025")
        assert len(matches) == 0


class TestNDISDetection:
    def setup_method(self):
        self.detector = PIIDetector("Jane Smith")

    def _ndis_matches(self, line):
        return [m for m in self.detector.detect_pii_in_text(line, 1) if m.category == "NDIS number"]

    def test_ndis_with_keyword_detected(self):
        matches = self._ndis_matches("NDIS number: 123456789")
        assert len(matches) == 1
        assert matches[0].text == "123456789"

    def test_ndis_participant_keyword_detected(self):
        matches = self._ndis_matches("Participant No. 987654321")
        assert len(matches) == 1

    def test_nine_digits_alone_not_detected(self):
        matches = self._ndis_matches("Reference 123456789 received")
        assert len(matches) == 0

    def test_eight_digits_with_keyword_not_detected(self):
        matches = self._ndis_matches("NDIS number: 12345678")
        assert len(matches) == 0


class TestABNDetection:
    def setup_method(self):
        self.detector = PIIDetector("Jane Smith")

    def _abn_matches(self, line):
        return [m for m in self.detector.detect_pii_in_text(line, 1) if m.category == "ABN"]

    def test_abn_with_keyword_detected(self):
        matches = self._abn_matches("ABN: 51 824 753 556")
        assert len(matches) == 1

    def test_abn_no_spaces_detected(self):
        matches = self._abn_matches("ABN: 51824753556")
        assert len(matches) == 1

    def test_eleven_digits_without_keyword_not_detected(self):
        matches = self._abn_matches("Number 51824753556 here")
        assert len(matches) == 0


class TestCrossLineDetection:
    def setup_method(self):
        self.detector = PIIDetector("Jane Smith")

    def test_dob_label_on_previous_line(self):
        text = "Date of Birth:\n15/03/2015"
        matches = [m for m in self.detector.detect_pii_in_text(text, 1) if m.category == "Date of birth"]
        assert len(matches) >= 1

    def test_medicare_keyword_on_previous_line(self):
        text = "Medicare Number:\n2345 67890 1"
        matches = [m for m in self.detector.detect_pii_in_text(text, 1) if m.category == "Medicare number"]
        assert len(matches) >= 1

    def test_mother_name_on_next_line(self):
        text = "Mother:\nSarah Williams"
        matches = [m for m in self.detector.detect_pii_in_text(text, 1)
                   if m.category in ("Parent/Guardian", "Family member")]
        assert len(matches) >= 1


class TestIntegration:
    def test_multi_pii_paragraph_all_detected(self):
        detector = PIIDetector("Alice Brown")
        text = "Student: Alice Brown. Phone: 0412 345 678. Email: alice.brown@example.com."
        matches = detector.detect_pii_in_text(text, 1)
        categories = [m.category for m in matches]
        assert 'Student name' in categories
        assert 'Phone number' in categories
        assert 'Email address' in categories

    def test_paragraph_with_no_pii_zero_matches(self):
        detector = PIIDetector("Alice Brown")
        text = "This document discusses general policy guidelines for all students."
        matches = detector.detect_pii_in_text(text, 1)
        assert len(matches) == 0

    def test_multi_line_text_pii_on_different_lines_all_detected(self):
        detector = PIIDetector("Alice Brown")
        text = (
            "Name: Alice Brown\n"
            "Phone: 02 9876 5432\n"
            "Email: alice@school.edu.au"
        )
        matches = detector.detect_pii_in_text(text, 1)
        categories = [m.category for m in matches]
        assert 'Student name' in categories
        assert 'Phone number' in categories
        assert 'Email address' in categories

    def test_word_boundary_jane_bloggs_detected_bloggsel_not(self):
        detector = PIIDetector("Jane Bloggs")
        text = "Jane Bloggs bought some bloggsel from the market."
        matches = detector.detect_pii_in_text(text, 1)
        name_texts = [m.text.lower() for m in matches if m.category == 'Student name']
        # "Jane Bloggs" or its parts must appear
        assert any('bloggs' == t or 'jane bloggs' == t or 'jane' == t for t in name_texts)
        # "bloggsel" must NOT appear as a student name match
        assert not any('bloggsel' in t for t in name_texts)
