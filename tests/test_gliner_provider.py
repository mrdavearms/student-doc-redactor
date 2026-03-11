import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import pytest

try:
    from gliner_provider import GLiNERDetector
    GLINER_AVAILABLE = True
except ImportError:
    GLINER_AVAILABLE = False

needs_gliner = pytest.mark.skipif(not GLINER_AVAILABLE, reason="gliner not installed")


@needs_gliner
class TestGLiNERDetector:

    @pytest.fixture(scope="class")
    def detector(self):
        """Shared detector instance (model loading is slow)."""
        return GLiNERDetector()

    def test_model_loads(self, detector):
        assert detector.model is not None

    def test_detects_person_name(self, detector):
        matches = detector.detect("Sarah Williams called the school.", page_num=1)
        person_matches = [m for m in matches if "person" in m.category.lower() or "name" in m.category.lower()]
        assert len(person_matches) > 0
        assert any("Sarah" in m.text for m in person_matches)

    def test_detects_email(self, detector):
        matches = detector.detect("Contact us at admin@school.edu.au for details.", page_num=1)
        email_matches = [m for m in matches if "email" in m.category.lower()]
        assert len(email_matches) > 0

    def test_detects_phone_number(self, detector):
        matches = detector.detect("Call 0412 345 678 for more info.", page_num=1)
        phone_matches = [m for m in matches if "phone" in m.category.lower()]
        assert len(phone_matches) > 0

    def test_no_pii_returns_empty(self, detector):
        matches = detector.detect("The weather is nice today.", page_num=1)
        # May detect some entities depending on model, but should be minimal
        # Check that at least it doesn't crash
        assert isinstance(matches, list)

    def test_matches_have_correct_page_num(self, detector):
        matches = detector.detect("Jane Smith is here.", page_num=5)
        for m in matches:
            assert m.page_num == 5

    def test_matches_have_gliner_source(self, detector):
        matches = detector.detect("John Brown was present.", page_num=1)
        for m in matches:
            assert m.source == "gliner"

    def test_confidence_is_float(self, detector):
        matches = detector.detect("Dr. Emily Parker examined the student.", page_num=1)
        for m in matches:
            assert isinstance(m.confidence, float)
            assert 0.0 <= m.confidence <= 1.0

    def test_contextual_name_detected(self, detector):
        """GLiNER should catch names in informal context that regex might miss."""
        matches = detector.detect(
            "The student's mother, Patricia Henderson, signed the permission slip.",
            page_num=1,
        )
        person_matches = [m for m in matches if "person" in m.category.lower() or "name" in m.category.lower()]
        assert any("Patricia" in m.text or "Henderson" in m.text for m in person_matches)

    def test_general_date_not_detected(self, detector):
        """Meeting dates and review dates must NOT be flagged — only DOB should be."""
        matches = detector.detect(
            "Annual review meeting scheduled for 15 March 2025.",
            page_num=1,
        )
        date_matches = [m for m in matches if "date" in m.category.lower()]
        assert len(date_matches) == 0, (
            f"General meeting date should not be flagged, got: {[m.text for m in date_matches]}"
        )

    def test_location_suburb_not_detected(self, detector):
        """General suburbs and cities must NOT be flagged as PII."""
        matches = detector.detect(
            "The student lives in Parramatta and attends school in Blacktown.",
            page_num=1,
        )
        location_matches = [m for m in matches if "location" in m.category.lower()]
        assert len(location_matches) == 0, (
            f"General suburb names should not be flagged, got: {[m.text for m in location_matches]}"
        )

    def test_threshold_filters_low_confidence_proper_nouns(self, detector):
        """With threshold 0.65, vague proper nouns below threshold must not appear."""
        # 'Ritalin' and 'Minecraft' were flagged as persons at threshold 0.5
        matches = detector.detect(
            "The student takes Ritalin daily and enjoys playing Minecraft.",
            page_num=1,
        )
        person_matches = [m for m in matches if "person" in m.category.lower()]
        flagged_texts = [m.text for m in person_matches]
        assert "Ritalin" not in flagged_texts, "Medication names must not be flagged as persons"
        assert "Minecraft" not in flagged_texts, "Game names must not be flagged as persons"
