import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import pytest
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
        matches = orch.detect_pii_in_text(text, page_num=1)
        sources = {m.source for m in matches}
        assert "regex" in sources
        # Presidio should also contribute (at minimum the phone or name)
        assert "presidio" in sources

    def test_graceful_degradation_without_presidio(self):
        """If Presidio is disabled, orchestrator still works with regex + GLiNER."""
        orch = PIIOrchestrator("Jane Smith")
        orch.presidio_analyzer = None
        matches = orch.detect_pii_in_text("Jane Smith is here.", page_num=1)
        assert len(matches) > 0
        # No match should come from presidio
        assert all(m.source != "presidio" for m in matches)
