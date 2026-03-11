"""
PII Orchestrator
Merges results from regex (PIIDetector), Presidio NER, and (optionally) GLiNER
into a single deduplicated list of PIIMatch objects.
"""

from typing import List, Optional
from pii_detector import PIIDetector, PIIMatch


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
    Optionally runs: Presidio (if installed), GLiNER (if installed)
    """

    def __init__(self, student_name: str, parent_names: List[str] = None, family_names: List[str] = None):
        self.student_name = student_name.strip()
        self.parent_names = parent_names or []
        self.family_names = family_names or []

        # Always create the regex detector
        self.regex_detector = PIIDetector(
            self.student_name,
            parent_names=self.parent_names,
            family_names=self.family_names,
        )

        # Try to initialise Presidio
        self.presidio_analyzer = None
        self._init_presidio()

        # Try to initialise GLiNER
        self.gliner_detector = None
        self._init_gliner()

    def _init_gliner(self):
        """Initialise GLiNER zero-shot NER detector."""
        try:
            from gliner_provider import GLiNERDetector
            self.gliner_detector = GLiNERDetector()
        except Exception:
            self.gliner_detector = None

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

        except Exception:
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

        # 1. Regex detector (always runs)
        regex_matches = self.regex_detector.detect_pii_in_text(text, page_num)
        all_matches.extend(regex_matches)

        # 2. Presidio (if available)
        if self.presidio_analyzer:
            presidio_matches = self._run_presidio(text, page_num)
            all_matches.extend(presidio_matches)

        # 3. GLiNER (if available)
        if self.gliner_detector:
            gliner_matches = self.gliner_detector.detect(text, page_num)
            all_matches.extend(gliner_matches)

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

                # Extract the matched text
                matched_text = text[result.start:result.end]

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
