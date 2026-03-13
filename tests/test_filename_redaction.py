"""Tests for strip_pii_from_filename — filename PII redaction."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.redactor import strip_pii_from_filename

BLOGGS_VARIATIONS = ["Joe Bloggs", "Joe", "Bloggs", "J. Bloggs", "J.F.", "JF"]


class TestStripPiiFromFilename:

    def test_name_in_prefix(self):
        result = strip_pii_from_filename(
            "Joe Bloggs DIP Vineland Report 2025", BLOGGS_VARIATIONS
        )
        assert result == "DIP Vineland Report 2025"

    def test_name_in_suffix(self):
        result = strip_pii_from_filename(
            "Vineland Report - Joe Bloggs", BLOGGS_VARIATIONS
        )
        assert result == "Vineland Report"

    def test_name_embedded_with_brackets(self):
        result = strip_pii_from_filename(
            "Behavior Management Plan - Joe Bloggs (T1 2024)", BLOGGS_VARIATIONS
        )
        assert result == "Behavior Management Plan (T1 2024)"

    def test_underscore_separated(self):
        result = strip_pii_from_filename(
            "Bloggs_Joe_Adaptive_Behaviour_Assessment_Summary", BLOGGS_VARIATIONS
        )
        assert result == "Adaptive Behaviour Assessment Summary"

    def test_parent_name_stripped(self):
        variations = BLOGGS_VARIATIONS + ["Mary Bloggs"]
        result = strip_pii_from_filename(
            "Overview of Joe's behaviours - Mary Bloggs", variations
        )
        assert result == "Overview of behaviours"

    def test_possessive_cleaned(self):
        result = strip_pii_from_filename(
            "Joe's Assessment Report", BLOGGS_VARIATIONS
        )
        assert result == "Assessment Report"

    def test_no_pii_passthrough(self):
        result = strip_pii_from_filename("AA report", BLOGGS_VARIATIONS)
        assert result == "AA report"

    def test_short_variation_not_stripped(self):
        # "JF" is 2 chars — must be skipped; "JFK" must not be touched
        result = strip_pii_from_filename("JFKAirport Report", BLOGGS_VARIATIONS)
        assert result == "JFKAirport Report"

    def test_empty_result_fallback(self):
        result = strip_pii_from_filename("Joe", BLOGGS_VARIATIONS)
        assert result == "document"

    def test_short_result_fallback(self):
        # After stripping, only "A" remains — too short, use fallback
        result = strip_pii_from_filename("Joe A", BLOGGS_VARIATIONS)
        assert result == "document"

    def test_empty_variations_passthrough(self):
        result = strip_pii_from_filename("Report 2025", [])
        assert result == "Report 2025"

    def test_longest_variation_matched_first(self):
        # "Joe Bloggs" stripped as a unit — result has no double-space
        result = strip_pii_from_filename(
            "Joe Bloggs Report", ["Joe Bloggs", "Joe", "Bloggs"]
        )
        assert result == "Report"

    def test_organisation_name_stripped(self):
        variations = BLOGGS_VARIATIONS + ["Greenwood PS", "Greenwood"]
        result = strip_pii_from_filename(
            "Joe Bloggs Greenwood PS Assessment", variations
        )
        assert "Greenwood" not in result
        assert "Assessment" in result
