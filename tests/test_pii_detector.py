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
