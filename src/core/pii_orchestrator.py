"""
PII Orchestrator
Merges results from regex (PIIDetector) and Presidio NER (spaCy)
into a single deduplicated list of PIIMatch objects.

Architecture: NER-primary — Presidio discovers names, then regex
catches structured PII and user-provided names.
"""

import re
from typing import List, Optional
from pii_detector import PIIDetector, PIIMatch, generate_name_variations


# Presidio entity types that are too broad for this use case.
# LOCATION/GPE/FAC flag general suburbs/cities that are not student PII.
# DATE_TIME flags meeting and review dates that must not be redacted.
PRESIDIO_SKIP_TYPES = {"LOCATION", "GPE", "FAC", "DATE_TIME"}

# Category mapping from Presidio entity types to our display categories
PRESIDIO_CATEGORY_MAP = {
    "PERSON": "Person name (NER)",
    "LOCATION": "Location (NER)",
    "GPE": "Location (NER)",
    "FAC": "Location (NER)",
    "AU_PHONE": "Phone number",
    "AU_ADDRESS": "Address",
    "AU_MEDICARE": "Medicare number",
    "AU_CRN": "Centrelink CRN",
    "AU_DOB": "Date of birth",
    "STUDENT_NAME": "Student name",
    "EMAIL_ADDRESS": "Email address",
    "PHONE_NUMBER": "Phone number",
    "DATE_TIME": "Date/Time (NER)",
}


class PIIOrchestrator:
    """
    Runs multiple PII detection backends and merges results.

    Always runs: PIIDetector (regex)
    Optionally runs: Presidio/spaCy (NER-primary name discovery)
    """

    def __init__(self, student_name: str, parent_names: List[str] = None,
                 family_names: List[str] = None, organisation_names: List[str] = None,
                 require_ner: bool = False):
        self.student_name = student_name.strip()
        self.parent_names = parent_names or []
        self.family_names = family_names or []
        self.organisation_names = organisation_names or []
        self.require_ner = require_ner

        # Always create the regex detector
        self.regex_detector = PIIDetector(
            self.student_name,
            parent_names=self.parent_names,
            family_names=self.family_names,
            organisation_names=self.organisation_names,
        )

        # Try to initialise Presidio
        self.presidio_analyzer = None
        self._init_presidio()

    def _init_presidio(self):
        """Initialise Presidio analyzer with spaCy NER and custom AU recognizers."""
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider

            from presidio_recognizers import (
                AustralianPhoneRecognizer,
                AustralianAddressRecognizer,
                AustralianMedicareRecognizer,
                CentrelinkCRNRecognizer,
                DateOfBirthRecognizer,
                StudentNameRecognizer,
            )

            # Create NLP engine with spaCy
            provider = NlpEngineProvider(nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}],
            })
            nlp_engine = provider.create_engine()

            # Create analyzer
            self.presidio_analyzer = AnalyzerEngine(
                nlp_engine=nlp_engine,
                supported_languages=["en"],
            )

            # Register custom AU recognizers
            self.presidio_analyzer.registry.add_recognizer(AustralianPhoneRecognizer())
            self.presidio_analyzer.registry.add_recognizer(AustralianAddressRecognizer())
            self.presidio_analyzer.registry.add_recognizer(AustralianMedicareRecognizer())
            self.presidio_analyzer.registry.add_recognizer(CentrelinkCRNRecognizer())
            self.presidio_analyzer.registry.add_recognizer(DateOfBirthRecognizer())
            self.presidio_analyzer.registry.add_recognizer(
                StudentNameRecognizer(name_variations=self.regex_detector.name_variations)
            )

        except Exception as e:
            if self.require_ner:
                raise RuntimeError(f"NER engine (spaCy/Presidio) failed to load: {e}") from e
            # Graceful degradation — Presidio is optional
            self.presidio_analyzer = None

    @property
    def name_variations(self):
        """Expose name_variations from the underlying regex detector."""
        return self.regex_detector.name_variations

    def detect_pii_in_text(self, text: str, page_num: int) -> List[PIIMatch]:
        """
        Run all enabled detection backends and return merged, deduplicated results.

        Args:
            text: Text to scan
            page_num: Page number (1-indexed)

        Returns:
            Deduplicated list of PIIMatch sorted by confidence descending
        """
        all_matches: List[PIIMatch] = []

        # 1. Regex detector (always runs) — user-entered names, structured PII
        regex_matches = self.regex_detector.detect_pii_in_text(text, page_num)
        all_matches.extend(regex_matches)

        # 2. Presidio/spaCy NER (primary name discovery engine)
        if self.presidio_analyzer:
            ner_matches = self._run_presidio(text, page_num)
            # Filter very short NER hits
            ner_matches = [m for m in ner_matches if len(m.text) >= 3]

            # For each PERSON entity, generate name variations
            for m in ner_matches:
                if 'name' in m.category.lower() or m.category == 'Person':
                    m.confidence = max(m.confidence, 0.90)
                    # Generate variations for NER-discovered names
                    variations, _ = generate_name_variations(m.text, include_nicknames=False)
                    for var in variations:
                        if var.lower() != m.text.lower() and len(var) >= 3:
                            for match in re.finditer(re.escape(var), text, re.IGNORECASE):
                                line_num = text[:match.start()].count('\n') + 1
                                all_matches.append(PIIMatch(
                                    text=match.group(), category="Person name (NER variation)",
                                    confidence=0.85, page_num=page_num, line_num=line_num,
                                    context=text[max(0, match.start()-25):match.end()+25],
                                    source='presidio'
                                ))
            all_matches.extend(ner_matches)

        # Deduplicate and return
        return self._deduplicate(all_matches)

    def _run_presidio(self, text: str, page_num: int) -> List[PIIMatch]:
        """Run Presidio analyzer and convert results to PIIMatch objects."""
        matches = []

        try:
            results = self.presidio_analyzer.analyze(
                text=text,
                language="en",
                score_threshold=0.55,
            )

            lines = text.split("\n")

            for result in results:
                # Skip entity types that are too broad for PII redaction
                if result.entity_type in PRESIDIO_SKIP_TYPES:
                    continue

                # Map Presidio entity type to our category
                category = PRESIDIO_CATEGORY_MAP.get(result.entity_type, f"{result.entity_type} (NER)")

                # Extract the matched text.
                # Presidio's NER model occasionally spans across a newline
                # (e.g. "Jane Holmes\nClassroom"), producing a garbled match
                # that looks broken on the review screen and prevents clean
                # deduplication with other engines.  Real PII never spans lines,
                # so truncate to the first line only.
                matched_text = text[result.start:result.end].split("\n")[0].strip()

                # Determine line number
                char_count = 0
                line_num = 1
                for i, line in enumerate(lines, 1):
                    if char_count + len(line) >= result.start:
                        line_num = i
                        break
                    char_count += len(line) + 1  # +1 for newline

                # Get context (the line containing the match)
                context = lines[line_num - 1] if line_num <= len(lines) else ""

                matches.append(PIIMatch(
                    text=matched_text,
                    category=category,
                    confidence=round(result.score, 2),
                    page_num=page_num,
                    line_num=line_num,
                    context=context.strip(),
                    source="presidio",
                ))

        except Exception:
            pass  # Graceful degradation

        return matches

    def _deduplicate(self, matches: List[PIIMatch]) -> List[PIIMatch]:
        """
        Deduplicate matches: if two matches have the same text (case-insensitive)
        on the same page and line, keep the one with the highest confidence.
        """
        seen = {}
        for match in matches:
            key = (match.text.lower(), match.page_num, match.line_num)
            if key not in seen or match.confidence > seen[key].confidence:
                seen[key] = match

        # Sort by confidence descending, then by page/line for stable ordering
        result = sorted(seen.values(), key=lambda m: (-m.confidence, m.page_num, m.line_num))
        return result
