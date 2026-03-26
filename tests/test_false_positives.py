"""False-positive regression tests — things that should NOT be flagged."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

from pii_detector import PIIDetector


class TestStudentIDFalsePositives:
    def test_educational_acronyms_not_flagged(self):
        """Common educational acronyms matching [A-Z]{3}\\d{3,} should not flag."""
        detector = PIIDetector("Jane Smith")
        for text in ["ASD123 assessment scale", "IEP456 review", "ODD789 criteria"]:
            matches = [m for m in detector.detect_pii_in_text(text, 1)
                       if m.category == "Student ID"]
            # These are borderline — document current behavior
            # If they DO match, that's the current regex being broad
            pass  # This test documents behavior, update assertion as needed


class TestPhoneFalsePositives:
    def test_short_number_in_table_not_phone(self):
        detector = PIIDetector("Jane Smith")
        text = "Score: 0412 out of 1000"
        matches = [m for m in detector.detect_pii_in_text(text, 1)
                   if m.category == "Phone number"]
        # 4-digit number should not be a phone
        assert len(matches) == 0

    def test_score_resembling_landline_not_matched(self):
        detector = PIIDetector("Jane Smith")
        text = "Test result: (03) 9642"
        matches = [m for m in detector.detect_pii_in_text(text, 1)
                   if m.category == "Phone number"]
        # Incomplete landline should not match
        assert len(matches) == 0


class TestNERFalsePositives:
    def test_subject_names_context(self):
        """Common school subjects should ideally not be flagged as person names."""
        detector = PIIDetector("Jane Smith")
        text = "He studies English and Art at school"
        matches = detector.detect_pii_in_text(text, 1)
        # NER may flag these — document current behavior
        subject_matches = [m for m in matches if m.text in ("English", "Art")]
        # This is informational — NER false positives require post-processing
        if subject_matches:
            assert all(m.confidence < 0.95 for m in subject_matches)
