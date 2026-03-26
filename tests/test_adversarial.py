"""Adversarial and edge-case input tests."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import fitz
import pytest
from pathlib import Path
from pii_detector import PIIDetector


class TestUnicodeEdgeCases:
    def test_zero_width_chars_in_name(self):
        detector = PIIDetector("Jane Smith")
        # Zero-width space between first and last name
        text = "Student: Jane\u200BSmith attended"
        matches = detector.detect_pii_in_text(text, 1)
        # After NFKC normalisation, zero-width space should be stripped
        matched_texts = {m.text.lower() for m in matches}
        assert "jane" in matched_texts or "janesmith" in matched_texts or "jane smith" in matched_texts

    def test_smart_quotes_in_name(self):
        detector = PIIDetector("O'Brien")
        text = "Student O\u2019Brien was present"  # Right single quote
        matches = detector.detect_pii_in_text(text, 1)
        assert any("brien" in m.text.lower() for m in matches)

    def test_ligature_in_name(self):
        detector = PIIDetector("Griffin")
        # ffi ligature (\ufb03) decomposes to "ffi" under NFKC
        text = "Student Gri\ufb03n was present"
        matches = detector.detect_pii_in_text(text, 1)
        # After NFKC, the ligature decomposes to "ffi" → "Griffin"
        assert any("griffin" in m.text.lower() for m in matches)


class TestBoundaryConditions:
    def test_pii_at_header_zone_boundary(self):
        """PII exactly at 12% mark — should be caught by zone or detection."""
        detector = PIIDetector("Jane Smith")
        text = "Jane Smith\n" * 3  # Name near the top
        matches = detector.detect_pii_in_text(text, 1)
        assert len(matches) >= 1

    def test_pii_on_last_line_of_page(self):
        detector = PIIDetector("Jane Smith")
        text = "Nothing here\n" * 50 + "Contact Jane Smith"
        matches = detector.detect_pii_in_text(text, 1)
        assert any("jane smith" in m.text.lower() for m in matches)

    def test_empty_text_no_crash(self):
        detector = PIIDetector("Jane Smith")
        matches = detector.detect_pii_in_text("", 1)
        assert matches == []

    def test_single_line_text(self):
        detector = PIIDetector("Jane Smith")
        matches = detector.detect_pii_in_text("Jane Smith", 1)
        assert len(matches) >= 1
