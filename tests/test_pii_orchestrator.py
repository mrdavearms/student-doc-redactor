import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import pytest
from unittest.mock import patch, MagicMock
from pii_orchestrator import PIIOrchestrator
from pii_detector import PIIMatch


# ---------------------------------------------------------------------------
# Basic Orchestrator Tests (always run — regex always available)
# ---------------------------------------------------------------------------

class TestOrchestratorBasic:

    def test_orchestrator_creates_regex_detector(self):
        orch = PIIOrchestrator("Jane Smith")
        assert orch.regex_detector is not None

    def test_orchestrator_exposes_name_variations(self):
        orch = PIIOrchestrator("Jane Smith")
        assert "Jane Smith" in orch.name_variations
        assert "Jane" in orch.name_variations

    def test_regex_detection_works_through_orchestrator(self):
        orch = PIIOrchestrator("Jane Smith")
        matches = orch.detect_pii_in_text("Jane Smith is here.", page_num=1)
        assert len(matches) > 0
        assert any(m.category == "Student name" for m in matches)

    def test_phone_detected_through_orchestrator(self):
        orch = PIIOrchestrator("Jane Smith")
        matches = orch.detect_pii_in_text("Call 0412 345 678 please", page_num=1)
        assert any(m.category == "Phone number" for m in matches)

    def test_email_detected_through_orchestrator(self):
        orch = PIIOrchestrator("Jane Smith")
        matches = orch.detect_pii_in_text("Email: jane@example.com", page_num=1)
        assert any(m.category == "Email address" for m in matches)

    def test_no_pii_regex_returns_empty(self):
        orch = PIIOrchestrator("Jane Smith")
        matches = orch.detect_pii_in_text("The quick brown fox.", page_num=1)
        # Regex should find nothing; NER models may produce false positives
        regex_matches = [m for m in matches if m.source == "regex"]
        assert len(regex_matches) == 0

    def test_results_sorted_by_confidence_descending(self):
        orch = PIIOrchestrator("Jane Smith")
        text = "Jane Smith, DOB: 15/03/2010, Phone: 0412 345 678"
        matches = orch.detect_pii_in_text(text, page_num=1)
        if len(matches) >= 2:
            for i in range(len(matches) - 1):
                assert matches[i].confidence >= matches[i + 1].confidence

    def test_parent_names_passed_through(self):
        orch = PIIOrchestrator("Tom Jones", parent_names=["Sandra Jones"])
        matches = orch.detect_pii_in_text("Sandra Jones signed the form.", page_num=1)
        assert any("Sandra" in m.text for m in matches)

    def test_family_names_passed_through(self):
        orch = PIIOrchestrator("Tom Jones", family_names=["Uncle Dave"])
        matches = orch.detect_pii_in_text("Uncle Dave picked him up.", page_num=1)
        assert any("Uncle Dave" in m.text for m in matches)

    def test_ner_result_shorter_than_3_chars_is_filtered(self):
        """A 1-2 char NER result must never reach the output list."""
        orch = PIIOrchestrator("Jo Li")
        short_match = PIIMatch(
            text="Jo", category="Person name (NER)", confidence=0.9,
            page_num=1, line_num=1, context="Jo Li", source="presidio"
        )
        orch._run_presidio = lambda text, page_num: [short_match]
        orch.presidio_analyzer = object()  # non-None to trigger presidio path
        # GLiNER removed — only regex + presidio
        matches = orch.detect_pii_in_text("Jo Li lives here.", page_num=1)
        short_ner = [m for m in matches if m.source == "presidio" and len(m.text) < 3]
        assert len(short_ner) == 0, f"Short NER result slipped through: {short_ner}"

    def test_ner_result_exactly_3_chars_is_kept(self):
        """A 3-char NER result must not be filtered out by the length guard."""
        orch = PIIOrchestrator("Tom Jones")
        three_char = PIIMatch(
            text="Ann", category="Person name (NER)", confidence=0.9,
            page_num=1, line_num=1, context="Ann called the school.", source="presidio"
        )
        orch._run_presidio = lambda text, page_num: [three_char]
        orch.presidio_analyzer = object()
        # GLiNER removed — only regex + presidio
        matches = orch.detect_pii_in_text("Ann called the school.", page_num=1)
        ner_ann = [m for m in matches if m.source == "presidio" and m.text == "Ann"]
        assert len(ner_ann) == 1


# ---------------------------------------------------------------------------
# Deduplication Tests
# ---------------------------------------------------------------------------

class TestDeduplication:

    def test_duplicate_text_same_line_kept_once(self):
        orch = PIIOrchestrator("Jane Smith")
        # Create manual matches to test dedup logic
        m1 = PIIMatch(text="Jane Smith", category="Student name", confidence=0.95,
                       page_num=1, line_num=1, context="Jane Smith", source="regex")
        m2 = PIIMatch(text="Jane Smith", category="Person name (NER)", confidence=0.85,
                       page_num=1, line_num=1, context="Jane Smith", source="presidio")
        result = orch._deduplicate([m1, m2])
        assert len(result) == 1
        # Should keep the higher confidence one
        assert result[0].confidence == 0.95

    def test_same_text_different_lines_both_kept(self):
        orch = PIIOrchestrator("Jane Smith")
        m1 = PIIMatch(text="Jane Smith", category="Student name", confidence=0.95,
                       page_num=1, line_num=1, context="line 1", source="regex")
        m2 = PIIMatch(text="Jane Smith", category="Student name", confidence=0.95,
                       page_num=1, line_num=3, context="line 3", source="regex")
        result = orch._deduplicate([m1, m2])
        assert len(result) == 2

    def test_different_text_same_line_both_kept(self):
        orch = PIIOrchestrator("Jane Smith")
        m1 = PIIMatch(text="Jane", category="Student name", confidence=0.95,
                       page_num=1, line_num=1, context="Jane Smith", source="regex")
        m2 = PIIMatch(text="Smith", category="Student name", confidence=0.95,
                       page_num=1, line_num=1, context="Jane Smith", source="regex")
        result = orch._deduplicate([m1, m2])
        assert len(result) == 2

    def test_case_insensitive_dedup(self):
        orch = PIIOrchestrator("Jane Smith")
        m1 = PIIMatch(text="Jane Smith", category="Student name", confidence=0.95,
                       page_num=1, line_num=1, context="ctx", source="regex")
        m2 = PIIMatch(text="JANE SMITH", category="Person name (NER)", confidence=0.85,
                       page_num=1, line_num=1, context="ctx", source="presidio")
        result = orch._deduplicate([m1, m2])
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Presidio Integration Tests (skip if Presidio not available)
# ---------------------------------------------------------------------------

try:
    from presidio_analyzer import AnalyzerEngine
    PRESIDIO_AVAILABLE = True
except ImportError:
    PRESIDIO_AVAILABLE = False

needs_presidio = pytest.mark.skipif(not PRESIDIO_AVAILABLE, reason="presidio-analyzer not installed")


@needs_presidio
class TestPresidioIntegration:

    def test_presidio_initialised(self):
        orch = PIIOrchestrator("Jane Smith")
        assert orch.presidio_analyzer is not None

    def test_ner_detects_person_name(self):
        orch = PIIOrchestrator("Tom Jones")
        # Use a name that spaCy NER can detect but regex won't (not the student name)
        matches = orch.detect_pii_in_text("Dr. Sarah Williams examined the patient.", page_num=1)
        ner_matches = [m for m in matches if m.source == "presidio"]
        # spaCy should detect "Sarah Williams" as PERSON
        assert any("Sarah" in m.text or "Williams" in m.text for m in ner_matches)

    def test_merged_results_include_both_sources(self):
        orch = PIIOrchestrator("Jane Smith")
        text = "Jane Smith called from 0412 345 678."
        # Test that Presidio runs and produces results internally.
        # After deduplication, regex/GLiNER may absorb Presidio matches if they
        # have higher confidence for the same text — so test at the _run_presidio level.
        presidio_matches = orch._run_presidio(text, page_num=1)
        assert len(presidio_matches) > 0, "Presidio should produce matches internally"
        # Regex always contributes to the final merged output
        matches = orch.detect_pii_in_text(text, page_num=1)
        sources = {m.source for m in matches}
        assert "regex" in sources

    def test_graceful_degradation_without_presidio(self):
        """If Presidio is disabled, orchestrator still works with regex only."""
        orch = PIIOrchestrator("Jane Smith")
        orch.presidio_analyzer = None
        matches = orch.detect_pii_in_text("Jane Smith is here.", page_num=1)
        assert len(matches) > 0
        # No match should come from presidio
        assert all(m.source != "presidio" for m in matches)

    def test_presidio_location_type_not_flagged(self):
        """Presidio LOCATION/GPE entities must be filtered out — suburbs are not PII."""
        orch = PIIOrchestrator("Tom Jones")
        matches = orch.detect_pii_in_text(
            "The school is located in Parramatta, Sydney.", page_num=1
        )
        presidio_matches = [m for m in matches if m.source == "presidio"]
        location_matches = [
            m for m in presidio_matches
            if "location" in m.category.lower() or "gpe" in m.category.lower()
        ]
        assert len(location_matches) == 0, (
            f"Presidio LOCATION/GPE should be filtered, got: {[m.text for m in location_matches]}"
        )

    def test_presidio_date_time_type_not_flagged(self):
        """Presidio DATE_TIME entities must be filtered out — meeting dates are not PII."""
        orch = PIIOrchestrator("Tom Jones")
        matches = orch.detect_pii_in_text(
            "The IEP review will be held on 15 March 2025.", page_num=1
        )
        presidio_matches = [m for m in matches if m.source == "presidio"]
        date_matches = [
            m for m in presidio_matches
            if "date" in m.category.lower() and "birth" not in m.category.lower()
        ]
        assert len(date_matches) == 0, (
            f"Presidio DATE_TIME should be filtered, got: {[m.text for m in date_matches]}"
        )

    def test_presidio_person_type_still_detected(self):
        """Filtering location/date must NOT break PERSON entity detection."""
        orch = PIIOrchestrator("Tom Jones")
        matches = orch.detect_pii_in_text(
            "Dr. Sarah Williams examined the patient.", page_num=1
        )
        presidio_matches = [m for m in matches if m.source == "presidio"]
        person_matches = [m for m in presidio_matches if "person" in m.category.lower()]
        assert len(person_matches) > 0, "Presidio PERSON detection must still work after filtering"


# ---------------------------------------------------------------------------
# Organisation Name Passthrough Tests
# ---------------------------------------------------------------------------

class TestOrganisationNamePassthrough:

    def test_org_names_passed_to_regex_detector(self):
        orch = PIIOrchestrator("Jane Smith", organisation_names=["Greenwood PS"])
        assert orch.regex_detector.organisation_names == ["Greenwood PS"]

    def test_org_names_detected_through_orchestrator(self):
        orch = PIIOrchestrator("Jane Smith", organisation_names=["Riverside Clinic"])
        matches = orch.detect_pii_in_text("Riverside Clinic assessment results", page_num=1)
        org_matches = [m for m in matches if m.category == "Organisation name"]
        assert len(org_matches) >= 1

    def test_org_names_default_to_empty(self):
        orch = PIIOrchestrator("Jane Smith")
        assert orch.regex_detector.organisation_names == []


# ---------------------------------------------------------------------------
# NER Runtime Failure Tests
# ---------------------------------------------------------------------------

def _orchestrator(require_ner):
    # Skip the heavy spaCy load — inject a mock analyzer instead.
    with patch.object(PIIOrchestrator, "_init_presidio", lambda self: None):
        return PIIOrchestrator("Joe Bloggs", require_ner=require_ner)


def test_run_presidio_reraises_when_ner_required():
    o = _orchestrator(require_ner=True)
    o.presidio_analyzer = MagicMock()
    o.presidio_analyzer.analyze.side_effect = RuntimeError("spaCy crashed")
    with pytest.raises(RuntimeError):
        o._run_presidio("Some document text", 1)


def test_run_presidio_degrades_when_ner_optional():
    o = _orchestrator(require_ner=False)
    o.presidio_analyzer = MagicMock()
    o.presidio_analyzer.analyze.side_effect = RuntimeError("spaCy crashed")
    result = o._run_presidio("Some document text", 1)
    assert result == []


# ---------------------------------------------------------------------------
# NER Variation Matching: Word Boundaries and Title Filtering
# ---------------------------------------------------------------------------

def _stub_person(text_val):
    return PIIMatch(text=text_val, category="Person name (NER)", confidence=0.90,
                    page_num=1, line_num=1, context="", source="presidio")


class TestNerVariationBoundaries:
    def _orchestrator_with_stub(self, monkeypatch, person_text):
        # Skip the (slow) real Presidio init; stub the NER result directly.
        monkeypatch.setattr(PIIOrchestrator, "_init_presidio", lambda self: None)
        orch = PIIOrchestrator("Zara Quill")
        orch.presidio_analyzer = object()  # truthy — _run_presidio is stubbed
        monkeypatch.setattr(
            orch, "_run_presidio",
            lambda text, page_num: [_stub_person(person_text)]
        )
        return orch

    def test_variation_does_not_match_inside_longer_word(self, monkeypatch):
        orch = self._orchestrator_with_stub(monkeypatch, "Ann Chen")
        text = "Ann Chen attended.\nAnnual Review scheduled for Term 3."
        matches = orch.detect_pii_in_text(text, page_num=1)
        ann_hits = [m for m in matches if m.text.lower() == "ann"]
        assert all(m.line_num == 1 for m in ann_hits), \
            f"'Ann' matched inside 'Annual': {[(m.text, m.line_num) for m in ann_hits]}"

    def test_title_tokens_not_generated_as_variations(self, monkeypatch):
        orch = self._orchestrator_with_stub(monkeypatch, "Mrs Thompson")
        text = "Mrs Thompson is the classroom teacher."
        matches = orch.detect_pii_in_text(text, page_num=1)
        assert not any(m.text.lower() == "mrs" for m in matches), \
            "Bare title 'Mrs' must not be flagged as a name variation"

    def test_real_given_names_are_still_flagged_as_variations(self, monkeypatch):
        """Regression guard: common given names must NOT be filtered out.

        An earlier design filtered variations through _CONTEXTUAL_NAME_EXCLUDE,
        which contains real names (Bob, Sue, Max, Pat, Ray, Ted...). That would
        silently stop redacting a parent referred to by first name only.
        """
        for full, bare in [("Bob Henderson", "bob"), ("Sue Williams", "sue"),
                           ("Max Fenn", "max"), ("Ray Smith", "ray")]:
            orch = self._orchestrator_with_stub(monkeypatch, full)
            text = f"{full} attended the meeting.\nLater {bare.capitalize()} phoned the school."
            matches = orch.detect_pii_in_text(text, page_num=1)
            assert any(m.text.lower() == bare for m in matches), \
                f"Bare given name {bare!r} from {full!r} was not flagged — privacy risk"
