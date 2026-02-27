import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import pytest

try:
    from presidio_analyzer import AnalyzerEngine
    from presidio_recognizers import (
        AustralianPhoneRecognizer,
        AustralianAddressRecognizer,
        AustralianMedicareRecognizer,
        CentrelinkCRNRecognizer,
        DateOfBirthRecognizer,
        StudentNameRecognizer,
    )
    PRESIDIO_AVAILABLE = True
except ImportError:
    PRESIDIO_AVAILABLE = False

needs_presidio = pytest.mark.skipif(not PRESIDIO_AVAILABLE, reason="presidio-analyzer not installed")


def _run_recognizer(recognizer, text):
    """Run a recognizer on text and return results."""
    return recognizer.analyze(text, entities=[], nlp_artifacts=None)


# ---------------------------------------------------------------------------
# Australian Phone Recognizer
# ---------------------------------------------------------------------------

@needs_presidio
class TestAustralianPhoneRecognizer:

    def test_mobile_with_spaces(self):
        rec = AustralianPhoneRecognizer()
        results = rec.analyze("Call 0412 345 678", rec.supported_entities, None)
        assert len(results) >= 1
        assert any(r.entity_type == "AU_PHONE" for r in results)

    def test_international_format(self):
        rec = AustralianPhoneRecognizer()
        results = rec.analyze("+61 2 9876 5432", rec.supported_entities, None)
        assert len(results) >= 1

    def test_landline(self):
        rec = AustralianPhoneRecognizer()
        results = rec.analyze("Phone: 02 9876 5432", rec.supported_entities, None)
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# Australian Address Recognizer
# ---------------------------------------------------------------------------

@needs_presidio
class TestAustralianAddressRecognizer:

    def test_vic_address(self):
        rec = AustralianAddressRecognizer()
        results = rec.analyze("12 Oak Street, Melbourne, VIC 3000", rec.supported_entities, None)
        assert len(results) == 1
        assert results[0].entity_type == "AU_ADDRESS"

    def test_nsw_address(self):
        rec = AustralianAddressRecognizer()
        results = rec.analyze("45 George Street, Sydney, NSW 2000", rec.supported_entities, None)
        assert len(results) == 1

    def test_no_state_no_match(self):
        rec = AustralianAddressRecognizer()
        results = rec.analyze("123 Some Place here", rec.supported_entities, None)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Medicare Recognizer
# ---------------------------------------------------------------------------

@needs_presidio
class TestAustralianMedicareRecognizer:

    def test_with_keyword_matches(self):
        rec = AustralianMedicareRecognizer()
        results = _run_recognizer(rec, "Medicare: 2123 45678 1")
        assert len(results) == 1
        assert results[0].entity_type == "AU_MEDICARE"

    def test_without_keyword_no_match(self):
        rec = AustralianMedicareRecognizer()
        results = _run_recognizer(rec, "Number is 2123 45678 1")
        assert len(results) == 0

    def test_no_spaces_with_keyword(self):
        rec = AustralianMedicareRecognizer()
        results = _run_recognizer(rec, "Medicare number is 2123456781")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# CRN Recognizer
# ---------------------------------------------------------------------------

@needs_presidio
class TestCentrelinkCRNRecognizer:

    def test_crn_with_keyword(self):
        rec = CentrelinkCRNRecognizer()
        results = _run_recognizer(rec, "CRN: ABC123456")
        assert len(results) == 1
        assert results[0].entity_type == "AU_CRN"

    def test_without_keyword_no_match(self):
        rec = CentrelinkCRNRecognizer()
        results = _run_recognizer(rec, "Code: ABC123456")
        assert len(results) == 0


# ---------------------------------------------------------------------------
# DOB Recognizer
# ---------------------------------------------------------------------------

@needs_presidio
class TestDateOfBirthRecognizer:

    def test_dob_with_label(self):
        rec = DateOfBirthRecognizer()
        results = _run_recognizer(rec, "DOB: 15/03/2010")
        assert len(results) == 1
        assert results[0].entity_type == "AU_DOB"

    def test_date_without_label_no_match(self):
        rec = DateOfBirthRecognizer()
        results = _run_recognizer(rec, "15/03/2010")
        assert len(results) == 0

    def test_born_label(self):
        rec = DateOfBirthRecognizer()
        results = _run_recognizer(rec, "Born: 15 March 2010")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Student Name Recognizer
# ---------------------------------------------------------------------------

@needs_presidio
class TestStudentNameRecognizer:

    def test_full_name_detected(self):
        rec = StudentNameRecognizer(name_variations=["Jane Smith", "Jane", "Smith", "J. Smith"])
        results = _run_recognizer(rec, "The student Jane Smith enrolled.")
        assert len(results) >= 1
        texts = [rec.name for _ in results]  # Check entity type
        assert all(r.entity_type == "STUDENT_NAME" for r in results)

    def test_first_name_detected(self):
        rec = StudentNameRecognizer(name_variations=["Jane Smith", "Jane", "Smith"])
        results = _run_recognizer(rec, "Jane attended class.")
        found_texts = ["Jane attended class."[r.start:r.end] for r in results]
        assert "Jane" in found_texts

    def test_no_match_for_different_name(self):
        rec = StudentNameRecognizer(name_variations=["Jane Smith", "Jane", "Smith"])
        results = _run_recognizer(rec, "Bob went to school.")
        assert len(results) == 0

    def test_short_variations_skipped(self):
        rec = StudentNameRecognizer(name_variations=["JS", "Jane Smith"])
        results = _run_recognizer(rec, "The JS library is great. Jane Smith is here.")
        # "JS" (2 chars) should be skipped
        texts = ["The JS library is great. Jane Smith is here."[r.start:r.end] for r in results]
        assert "JS" not in texts
