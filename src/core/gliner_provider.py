"""
GLiNER Zero-Shot NER Provider
Uses the GLiNER PII model to detect entities that regex and traditional NER miss.
"""

from typing import List, Optional


# Category mapping from GLiNER labels to our display categories
GLINER_CATEGORY_MAP = {
    "person": "Person name (NER)",
    "address": "Address (NER)",
    "phone number": "Phone number (NER)",
    "email": "Email address (NER)",
    "date of birth": "Date of birth (NER)",
    "identification number": "ID number (NER)",
    "social security number": "ID number (NER)",
    "credit card number": "Financial (NER)",
    "passport number": "ID number (NER)",
    "date": "Date (NER)",
    "location": "Location (NER)",
    "organization": "Organization (NER)",
}

# Entity labels to request from GLiNER
ENTITY_LABELS = [
    "person",
    "address",
    "phone number",
    "email",
    "date of birth",
    "identification number",
    "date",
    "location",
]


class GLiNERDetector:
    """Wraps GLiNER zero-shot NER for PII detection."""

    def __init__(self, model_name: str = "urchade/gliner_multi_pii-v1", threshold: float = 0.5):
        self.model_name = model_name
        self.threshold = threshold
        self.model = None
        self._load_model()

    def _load_model(self):
        """Load the GLiNER model. May take 10-20s on first run."""
        try:
            from gliner import GLiNER
            self.model = GLiNER.from_pretrained(self.model_name)
        except Exception:
            self.model = None

    def detect(self, text: str, page_num: int) -> list:
        """
        Detect PII entities in text using GLiNER.

        Args:
            text: Text to scan
            page_num: Page number (1-indexed)

        Returns:
            List of PIIMatch objects
        """
        if self.model is None:
            return []

        # Import here to avoid circular imports — handle both direct and package usage
        try:
            from pii_detector import PIIMatch
        except ImportError:
            from src.core.pii_detector import PIIMatch

        matches = []
        lines = text.split("\n")

        try:
            entities = self.model.predict_entities(
                text,
                ENTITY_LABELS,
                threshold=self.threshold,
            )

            for entity in entities:
                matched_text = entity["text"]
                label = entity["label"]
                score = entity["score"]

                # Map label to our category
                category = GLINER_CATEGORY_MAP.get(label, f"{label} (NER)")

                # Determine line number from the entity's position in the text
                # GLiNER returns start/end character positions
                start_pos = entity.get("start", 0)
                char_count = 0
                line_num = 1
                for i, line in enumerate(lines, 1):
                    if char_count + len(line) >= start_pos:
                        line_num = i
                        break
                    char_count += len(line) + 1  # +1 for newline

                context = lines[line_num - 1] if line_num <= len(lines) else ""

                matches.append(PIIMatch(
                    text=matched_text,
                    category=category,
                    confidence=round(score, 2),
                    page_num=page_num,
                    line_num=line_num,
                    context=context.strip(),
                    source="gliner",
                ))

        except Exception:
            pass  # Graceful degradation

        return matches
