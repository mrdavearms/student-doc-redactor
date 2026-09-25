"""
The case rule for matching a PII string (rule 7) must be asked in ONE place.

Detection, both redactors, both verifiers and de-identification all agree on
whether a string matches regardless of case. If one site keeps its own answer,
it offers rows the redactor will not act on, or a correctly redacted file
quarantines itself.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import pii_detector
from pii_detector import PIIDetector


def _case_sensitive_everywhere(monkeypatch):
    """Make the shared rule say "exact case" for every string."""
    monkeypatch.setattr(pii_detector, 'match_flags', lambda text: 0)
    try:
        import presidio_recognizers
        monkeypatch.setattr(presidio_recognizers, 'match_flags', lambda text: 0)
    except ImportError:
        pass


class TestEveryDetectionSiteUsesTheSharedRule:
    """Each test patches the shared rule and checks the site obeys it. A site
    that hard-codes IGNORECASE still finds the lowercase word and fails."""

    def test_student_nicknames(self, monkeypatch):
        _case_sensitive_everywhere(monkeypatch)
        detector = PIIDetector("Christopher Brown")
        # The nickname map stores its names in lowercase, so under an
        # exact-case rule "chris" no longer matches the capitalised "Chris".
        assert 'chris' in detector._nickname_variations
        found = [m.text for m in detector.detect_pii_in_text("Chris was late", 1)]
        assert 'Chris' not in found

    def test_organisation_full_name(self, monkeypatch):
        _case_sensitive_everywhere(monkeypatch)
        detector = PIIDetector("Billy Bob", organisation_names=["Riverside Clinic"])
        found = [m.text for m in detector.detect_pii_in_text("seen at riverside clinic", 1)]
        assert found == []

    def test_organisation_single_words(self, monkeypatch):
        _case_sensitive_everywhere(monkeypatch)
        detector = PIIDetector("Billy Bob", organisation_names=["Riverside Clinic"])
        found = [m.text for m in detector.detect_pii_in_text("the riverside path", 1)]
        assert found == []

    def test_presidio_student_name_recogniser(self, monkeypatch):
        import pytest
        presidio_recognizers = pytest.importorskip('presidio_recognizers')
        _case_sensitive_everywhere(monkeypatch)
        recogniser = presidio_recognizers.StudentNameRecognizer(["Billy Bob", "Billy"])
        assert recogniser.analyze("billy bob went home", ["STUDENT_NAME"]) == []
        assert len(recogniser.analyze("Billy Bob went home", ["STUDENT_NAME"])) == 2
