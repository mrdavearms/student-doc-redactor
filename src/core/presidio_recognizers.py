"""
Custom Presidio Recognizers for Australian PII
Wraps AU-specific patterns as Presidio-compatible recognizers.
"""

from typing import List, Optional
from presidio_analyzer import PatternRecognizer, Pattern, EntityRecognizer, RecognizerResult, AnalysisExplanation
from presidio_analyzer.nlp_engine import NlpArtifacts


class AustralianPhoneRecognizer(PatternRecognizer):
    """Detects Australian phone numbers."""

    PATTERNS = [
        Pattern("AU_PHONE_INTL_MOBILE", r"\+61\s*4\d{2}\s*\d{3}\s*\d{3}", 0.85),
        Pattern("AU_PHONE_INTL", r"\+61\s*[2-478]\s*\d{4}\s*\d{4}", 0.85),
        Pattern("AU_PHONE_LANDLINE", r"0[2-478]\s*\d{4}\s*\d{4}", 0.85),
        Pattern("AU_PHONE_LANDLINE_DOTTED", r"(?<!\d\.)0[2-478]\.\d{4}\.\d{4}(?!\d)", 0.85),
        Pattern("AU_PHONE_PARENS", r"\(0[2-478]\)\s*\d{4}\s*\d{4}", 0.85),
        Pattern("AU_PHONE_MOBILE_SPACED", r"04\d{2}\s*\d{3}\s*\d{3}", 0.85),
        Pattern("AU_PHONE_MOBILE_DOTTED", r"(?<!\d\.)04\d{2}\.\d{3}\.\d{3}(?!\d)", 0.85),
        Pattern("AU_PHONE_MOBILE_NOSPACE", r"04\d{8}", 0.80),
    ]

    def __init__(self):
        super().__init__(
            supported_entity="AU_PHONE",
            patterns=self.PATTERNS,
            supported_language="en",
            name="AU Phone Recognizer",
        )


class AustralianAddressRecognizer(PatternRecognizer):
    """Detects Australian street addresses with state and postcode."""

    PATTERNS = [
        Pattern(
            "AU_ADDRESS",
            # Presidio compiles patterns with DOTALL|MULTILINE|IGNORECASE, so
            # the free-text runs must not cross a line break ([A-Za-z ] rather
            # than [A-Za-z\s]) and the state is matched as written ((?-i:…)),
            # or "3 sessions this term in the way\nthat was agreed with the
            # NSW 2024 planning group" is an address.
            r"(?:(?:Unit|Flat|Apt|Apartment) )?(?:\d+[A-Za-z]? ?/ ?)?\d+ [A-Za-z ]+(?:Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Court|Ct|Place|Pl|Lane|Ln|Way|Crescent|Cres|Boulevard|Blvd|Terrace|Tce|Close|Cl|Grove|Gr|Highway|Hwy|Parade|Pde|Circuit|Cct|Loop|Rise|Vale|Mews|Esplanade|Esp),? [A-Za-z ]+,? (?-i:VIC|Vic|NSW|Nsw|QLD|Qld|SA|WA|TAS|Tas|NT|ACT) \d{4}",
            0.85,
        ),
    ]

    def __init__(self):
        super().__init__(
            supported_entity="AU_ADDRESS",
            patterns=self.PATTERNS,
            supported_language="en",
            name="AU Address Recognizer",
        )


class AustralianMedicareRecognizer(EntityRecognizer):
    """Detects Medicare numbers (10-digit with specific grouping) only when preceded by a keyword."""

    KEYWORDS = ["medicare"]

    def __init__(self):
        super().__init__(
            supported_entities=["AU_MEDICARE"],
            supported_language="en",
            name="AU Medicare Recognizer",
        )

    def load(self):
        pass

    def analyze(self, text: str, entities: List[str], nlp_artifacts: NlpArtifacts = None) -> List[RecognizerResult]:
        import re
        results = []
        text_lower = text.lower()

        if not any(kw in text_lower for kw in self.KEYWORDS):
            return results

        pattern = re.compile(r"\b\d{4}\s?\d{5}\s?\d\b")
        for match in pattern.finditer(text):
            results.append(
                RecognizerResult(
                    entity_type="AU_MEDICARE",
                    start=match.start(),
                    end=match.end(),
                    score=0.9,
                    analysis_explanation=AnalysisExplanation(
                        recognizer=self.__class__.__name__,
                        original_score=0.9,
                        pattern_name="AU_MEDICARE",
                        pattern=pattern.pattern,
                    ),
                )
            )
        return results


class CentrelinkCRNRecognizer(EntityRecognizer):
    """Detects Centrelink Customer Reference Numbers — 9 alphanumeric chars after a CRN keyword."""

    KEYWORDS = ["crn", "customer reference"]

    def __init__(self):
        super().__init__(
            supported_entities=["AU_CRN"],
            supported_language="en",
            name="AU CRN Recognizer",
        )

    def load(self):
        pass

    def analyze(self, text: str, entities: List[str], nlp_artifacts: NlpArtifacts = None) -> List[RecognizerResult]:
        import re
        results = []
        text_lower = text.lower()

        if not any(kw in text_lower for kw in self.KEYWORDS):
            return results

        pattern = re.compile(r"\b\d{3}[\s\-]?\d{3}[\s\-]?\d{3}[A-Za-z]\b|\b[A-Z0-9]{9}\b")
        for match in pattern.finditer(text):
            results.append(
                RecognizerResult(
                    entity_type="AU_CRN",
                    start=match.start(),
                    end=match.end(),
                    score=0.85,
                    analysis_explanation=AnalysisExplanation(
                        recognizer=self.__class__.__name__,
                        original_score=0.85,
                        pattern_name="AU_CRN",
                        pattern=pattern.pattern,
                    ),
                )
            )
        return results


class DateOfBirthRecognizer(EntityRecognizer):
    """Detects dates of birth — only when preceded by a DOB-related label."""

    # Whole words only — "Born" must not fire on "Osborne" or "stubborn".
    DOB_LABELS = [r"\bDOB\b", r"\bD\.O\.B\.?", r"\bDate of Birth\b", r"\bBorn\b", r"\bBirth Date\b"]
    _MONTHS = (
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    )
    DATE_PATTERNS = [
        r"\d{1,2}/\d{1,2}/\d{2,4}",
        r"\d{1,2}-\d{1,2}-\d{2,4}",
        r"\d{1,2}\.\d{1,2}\.\d{2,4}",
        r"\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTHS + r"\s+\d{2,4}",
        _MONTHS + r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{2,4}",
    ]

    def __init__(self):
        super().__init__(
            supported_entities=["AU_DOB"],
            supported_language="en",
            name="AU DOB Recognizer",
        )

    def load(self):
        pass

    def analyze(self, text: str, entities: List[str], nlp_artifacts: NlpArtifacts = None) -> List[RecognizerResult]:
        import re
        results = []

        # The label and the date must share a LINE, as in PIIDetector._detect_dob.
        # Checking the whole page turned every assessment and review date on a
        # page that mentioned "DOB" anywhere into a date of birth.
        offset = 0
        for line in text.split("\n"):
            has_label = any(re.search(label_pat, line, re.IGNORECASE)
                            for label_pat in self.DOB_LABELS)
            if has_label:
                for date_pat in self.DATE_PATTERNS:
                    for match in re.finditer(date_pat, line):
                        results.append(
                            RecognizerResult(
                                entity_type="AU_DOB",
                                start=offset + match.start(),
                                end=offset + match.end(),
                                score=0.9,
                                analysis_explanation=AnalysisExplanation(
                                    recognizer=self.__class__.__name__,
                                    original_score=0.9,
                                    pattern_name="AU_DOB",
                                    pattern=date_pat,
                                ),
                            )
                        )
            offset += len(line) + 1

        return results


class StudentNameRecognizer(EntityRecognizer):
    """Detects student name variations using the provided name list."""

    def __init__(self, name_variations: List[str] = None):
        super().__init__(
            supported_entities=["STUDENT_NAME"],
            supported_language="en",
            name="Student Name Recognizer",
        )
        self.name_variations = name_variations or []

    def load(self):
        pass

    def analyze(self, text: str, entities: List[str], nlp_artifacts: NlpArtifacts = None) -> List[RecognizerResult]:
        import re
        results = []
        text_lower = text.lower()

        for variation in self.name_variations:
            if len(variation) < 3:
                continue
            pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(variation) + r"(?![A-Za-z0-9])",
                                 re.IGNORECASE)
            for match in pattern.finditer(text):
                results.append(
                    RecognizerResult(
                        entity_type="STUDENT_NAME",
                        start=match.start(),
                        end=match.end(),
                        score=0.95,
                        analysis_explanation=AnalysisExplanation(
                            recognizer=self.__class__.__name__,
                            original_score=0.95,
                            pattern_name="STUDENT_NAME",
                            pattern=pattern.pattern,
                        ),
                    )
                )
        return results
