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


import case_rules
from case_rules import EXACT, IGNORE, NOT_LOWERCASE, case_allows, case_mode


class TestCaseMode:
    """The predicate itself. The word list is patched so these tests do not
    depend on what the shipped list happens to contain."""

    @staticmethod
    def _words(monkeypatch):
        monkeypatch.setattr(case_rules, 'COMMON_WORDS', frozenset({'young', 'will', 'long'}))

    def test_two_letters_are_exact(self, monkeypatch):
        self._words(monkeypatch)
        assert case_mode('Do') == EXACT
        assert case_mode(' Li ') == EXACT

    def test_single_common_word(self, monkeypatch):
        self._words(monkeypatch)
        assert case_mode('Young') == NOT_LOWERCASE
        assert case_mode('YOUNG') == NOT_LOWERCASE
        assert case_mode('young') == NOT_LOWERCASE

    def test_single_uncommon_word(self, monkeypatch):
        self._words(monkeypatch)
        assert case_mode('Nguyen') == IGNORE

    def test_multi_token_is_never_a_common_word(self, monkeypatch):
        self._words(monkeypatch)
        assert case_mode('Will Young') == IGNORE
        assert case_mode('W. Young') == IGNORE

    def test_hyphenated_and_possessive_forms_are_not_single_words(self, monkeypatch):
        self._words(monkeypatch)
        assert case_mode('Young-Long') == IGNORE
        assert case_mode("Young's") == IGNORE

    def test_case_allows_rejects_only_all_lowercase(self, monkeypatch):
        self._words(monkeypatch)
        assert case_allows('Young', 'Young')
        assert case_allows('Young', 'YOUNG')
        assert case_allows('Young', "Young's,")
        assert not case_allows('Young', 'young')
        assert not case_allows('Young', "young's")
        # The rule belongs to the PII string, however the user typed it.
        assert not case_allows('young', 'young')
        assert case_allows('young', 'Young')

    def test_case_allows_leaves_other_modes_alone(self, monkeypatch):
        self._words(monkeypatch)
        assert case_allows('Nguyen', 'nguyen')
        assert case_allows('Will Young', 'will young')
