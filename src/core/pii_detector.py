"""
PII Detection Engine
Detects personally identifiable information using regex patterns and contextual rules.
"""

import re
from typing import List, Dict, Tuple
from dataclasses import dataclass

@dataclass
class PIIMatch:
    """Represents a detected PII item"""
    text: str
    category: str
    confidence: str  # 'high', 'medium', 'low'
    page_num: int
    line_num: int
    context: str  # Surrounding text for display
    bbox: Tuple[float, float, float, float] = None  # Bounding box coordinates (x0, y0, x1, y1)

class PIIDetector:
    """Detects PII in text using pattern matching and contextual analysis"""

    # Australian phone number patterns
    PHONE_PATTERNS = [
        r'\+61\s*[2-478]\s*\d{4}\s*\d{4}',  # +61 2 1234 5678
        r'0[2-478]\s*\d{4}\s*\d{4}',  # 02 1234 5678
        r'\(0[2-478]\)\s*\d{4}\s*\d{4}',  # (02) 1234 5678
        r'04\d{2}\s*\d{3}\s*\d{3}',  # 0412 345 678
        r'04\d{8}',  # 0412345678
    ]

    # Email pattern
    EMAIL_PATTERN = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

    # Australian address pattern
    ADDRESS_PATTERN = r'\d+\s+[A-Za-z\s]+(?:Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Court|Ct|Place|Pl|Lane|Ln|Way|Crescent|Cres|Boulevard|Blvd|Terrace|Tce),?\s+[A-Za-z\s]+,?\s+(?:VIC|NSW|QLD|SA|WA|TAS|NT|ACT|Victoria|New South Wales|Queensland|South Australia|Western Australia|Tasmania|Northern Territory|Australian Capital Territory)\s+\d{4}'

    # Medicare number pattern
    MEDICARE_PATTERN = r'\d{4}\s*\d{5}\s*\d{1}'

    # Centrelink CRN pattern
    CRN_PATTERN = r'\b[A-Z0-9]{9}\b'

    # Student ID pattern (3 uppercase letters + digits)
    STUDENT_ID_PATTERN = r'\b[A-Z]{3}\d+\b'

    # DOB label patterns (must precede date)
    DOB_LABELS = [
        r'DOB',
        r'D\.O\.B\.',
        r'Date of Birth',
        r'Born',
        r'Birth Date',
        r'Date of birth'
    ]

    # Date patterns (various formats)
    DATE_PATTERNS = [
        r'\d{1,2}/\d{1,2}/\d{4}',  # DD/MM/YYYY
        r'\d{1,2}-\d{1,2}-\d{4}',  # DD-MM-YYYY
        r'\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}',  # DD Month YYYY
    ]

    # Contextual keywords for family member detection
    FAMILY_KEYWORDS = [
        r'Mother',
        r'Father',
        r'Parent',
        r'Guardian',
        r'Mum',
        r'Dad',
        r'Step-mother',
        r'Step-father',
        r'Step-parent',
        r'Carer',
        r'Caregiver',
        r'Emergency Contact',
        r'Next of Kin',
        r'Brother',
        r'Sister',
        r'Sibling',
        r'Family member',
        r'Lives with',
        r'Referred by parent',
        r'Parent/Guardian signature'
    ]

    def __init__(self, student_name: str, parent_names: List[str] = None, family_names: List[str] = None):
        """
        Initialize the PII detector

        Args:
            student_name: Full name of the student
            parent_names: List of parent/guardian names
            family_names: List of other family member names
        """
        self.student_name = student_name.strip()
        self.parent_names = [n.strip() for n in (parent_names or [])]
        self.family_names = [n.strip() for n in (family_names or [])]

        # Generate name variations
        self.name_variations = self._generate_name_variations()

    def _generate_name_variations(self) -> List[str]:
        """Generate variations of the student name (first, last, initials, etc.)"""
        variations = [self.student_name]

        name_parts = self.student_name.split()
        if len(name_parts) >= 2:
            # First name only
            variations.append(name_parts[0])
            # Last name only
            variations.append(name_parts[-1])
            # First initial + last name (e.g., J. Smith)
            variations.append(f"{name_parts[0][0]}. {name_parts[-1]}")
            # First name + last initial (e.g., John S.)
            variations.append(f"{name_parts[0]} {name_parts[-1][0]}.")
            # Initials (e.g., J.S., JS)
            initials = ''.join([part[0] for part in name_parts])
            variations.append(f"{initials[0]}.{initials[1]}.")
            variations.append(initials)

        # Add fuzzy variations (common misspellings/variations)
        # For now, just exact matches - fuzzy logic can be added later

        return variations

    def detect_pii_in_text(self, text: str, page_num: int) -> List[PIIMatch]:
        """
        Detect all PII in the given text

        Args:
            text: Text to analyze
            page_num: Page number in document

        Returns:
            List of PIIMatch objects
        """
        matches = []

        lines = text.split('\n')
        for line_num, line in enumerate(lines, 1):
            # Detect student name and variations
            matches.extend(self._detect_names(line, page_num, line_num))

            # Detect phone numbers
            matches.extend(self._detect_phones(line, page_num, line_num))

            # Detect emails
            matches.extend(self._detect_emails(line, page_num, line_num))

            # Detect addresses
            matches.extend(self._detect_addresses(line, page_num, line_num))

            # Detect Medicare numbers
            matches.extend(self._detect_medicare(line, page_num, line_num))

            # Detect CRN
            matches.extend(self._detect_crn(line, page_num, line_num))

            # Detect student IDs
            matches.extend(self._detect_student_id(line, page_num, line_num))

            # Detect DOB (context-sensitive)
            matches.extend(self._detect_dob(line, page_num, line_num))

            # Detect contextual family names
            matches.extend(self._detect_contextual_names(line, page_num, line_num))

        return matches

    def _detect_names(self, line: str, page_num: int, line_num: int) -> List[PIIMatch]:
        """Detect student name variations"""
        matches = []
        for variation in self.name_variations:
            pattern = re.compile(r'\b' + re.escape(variation) + r'\b', re.IGNORECASE)
            for match in pattern.finditer(line):
                context = self._get_context(line, match.start(), match.end())
                matches.append(PIIMatch(
                    text=match.group(),
                    category='Student name',
                    confidence='high',
                    page_num=page_num,
                    line_num=line_num,
                    context=context
                ))
        return matches

    def _detect_phones(self, line: str, page_num: int, line_num: int) -> List[PIIMatch]:
        """Detect Australian phone numbers"""
        matches = []
        for pattern_str in self.PHONE_PATTERNS:
            pattern = re.compile(pattern_str)
            for match in pattern.finditer(line):
                context = self._get_context(line, match.start(), match.end())
                matches.append(PIIMatch(
                    text=match.group(),
                    category='Phone number',
                    confidence='high',
                    page_num=page_num,
                    line_num=line_num,
                    context=context
                ))
        return matches

    def _detect_emails(self, line: str, page_num: int, line_num: int) -> List[PIIMatch]:
        """Detect email addresses"""
        matches = []
        pattern = re.compile(self.EMAIL_PATTERN)
        for match in pattern.finditer(line):
            context = self._get_context(line, match.start(), match.end())
            matches.append(PIIMatch(
                text=match.group(),
                category='Email address',
                confidence='high',
                page_num=page_num,
                line_num=line_num,
                context=context
            ))
        return matches

    def _detect_addresses(self, line: str, page_num: int, line_num: int) -> List[PIIMatch]:
        """Detect Australian addresses"""
        matches = []
        pattern = re.compile(self.ADDRESS_PATTERN, re.IGNORECASE)
        for match in pattern.finditer(line):
            context = self._get_context(line, match.start(), match.end())
            matches.append(PIIMatch(
                text=match.group(),
                category='Address',
                confidence='high',
                page_num=page_num,
                line_num=line_num,
                context=context
            ))
        return matches

    def _detect_medicare(self, line: str, page_num: int, line_num: int) -> List[PIIMatch]:
        """Detect Medicare numbers"""
        matches = []
        pattern = re.compile(self.MEDICARE_PATTERN)
        for match in pattern.finditer(line):
            context = self._get_context(line, match.start(), match.end())
            matches.append(PIIMatch(
                text=match.group(),
                category='Medicare number',
                confidence='high',
                page_num=page_num,
                line_num=line_num,
                context=context
            ))
        return matches

    def _detect_crn(self, line: str, page_num: int, line_num: int) -> List[PIIMatch]:
        """Detect Centrelink CRN"""
        matches = []
        pattern = re.compile(self.CRN_PATTERN)
        for match in pattern.finditer(line):
            # Check if it looks like a CRN (not just any 9 alphanumeric string)
            if 'CRN' in line.upper():
                context = self._get_context(line, match.start(), match.end())
                matches.append(PIIMatch(
                    text=match.group(),
                    category='Centrelink CRN',
                    confidence='medium',
                    page_num=page_num,
                    line_num=line_num,
                    context=context
                ))
        return matches

    def _detect_student_id(self, line: str, page_num: int, line_num: int) -> List[PIIMatch]:
        """Detect student ID (3 letters + digits)"""
        matches = []
        pattern = re.compile(self.STUDENT_ID_PATTERN)
        for match in pattern.finditer(line):
            # Check if first 3 letters match student surname
            id_text = match.group()
            surname_prefix = self.student_name.split()[-1][:3].upper() if ' ' in self.student_name else self.student_name[:3].upper()

            confidence = 'high' if id_text[:3] == surname_prefix else 'medium'
            context = self._get_context(line, match.start(), match.end())
            matches.append(PIIMatch(
                text=match.group(),
                category='Student ID',
                confidence=confidence,
                page_num=page_num,
                line_num=line_num,
                context=context
            ))
        return matches

    def _detect_dob(self, line: str, page_num: int, line_num: int) -> List[PIIMatch]:
        """Detect date of birth (only when preceded by label)"""
        matches = []

        # Check if line contains DOB label
        has_dob_label = any(re.search(label, line, re.IGNORECASE) for label in self.DOB_LABELS)

        if has_dob_label:
            # Look for dates in this line
            for date_pattern in self.DATE_PATTERNS:
                pattern = re.compile(date_pattern)
                for match in pattern.finditer(line):
                    context = self._get_context(line, match.start(), match.end())
                    matches.append(PIIMatch(
                        text=match.group(),
                        category='Date of birth',
                        confidence='high',
                        page_num=page_num,
                        line_num=line_num,
                        context=context
                    ))
        return matches

    def _detect_contextual_names(self, line: str, page_num: int, line_num: int) -> List[PIIMatch]:
        """Detect names appearing after contextual keywords"""
        matches = []

        # Check for family keywords
        for keyword in self.FAMILY_KEYWORDS:
            pattern = re.compile(keyword + r'[:\s]+([A-Z][a-z]+(?: [A-Z][a-z]+)*)', re.IGNORECASE)
            for match in pattern.finditer(line):
                name = match.group(1)
                # Skip if it's a known professional title or common word
                if name.lower() not in ['dr', 'mr', 'mrs', 'ms', 'miss', 'the', 'and', 'or']:
                    context = self._get_context(line, match.start(1), match.end(1))
                    category = 'Parent/Guardian' if any(k in keyword.lower() for k in ['mother', 'father', 'parent', 'mum', 'dad', 'guardian', 'carer']) else 'Family member'
                    matches.append(PIIMatch(
                        text=name,
                        category=category,
                        confidence='medium',
                        page_num=page_num,
                        line_num=line_num,
                        context=context
                    ))

        # Also check user-provided parent/family names
        for parent_name in self.parent_names:
            pattern = re.compile(r'\b' + re.escape(parent_name) + r'\b', re.IGNORECASE)
            for match in pattern.finditer(line):
                context = self._get_context(line, match.start(), match.end())
                matches.append(PIIMatch(
                    text=match.group(),
                    category='Parent/Guardian (user-provided)',
                    confidence='high',
                    page_num=page_num,
                    line_num=line_num,
                    context=context
                ))

        for family_name in self.family_names:
            pattern = re.compile(r'\b' + re.escape(family_name) + r'\b', re.IGNORECASE)
            for match in pattern.finditer(line):
                context = self._get_context(line, match.start(), match.end())
                matches.append(PIIMatch(
                    text=match.group(),
                    category='Family member (user-provided)',
                    confidence='high',
                    page_num=page_num,
                    line_num=line_num,
                    context=context
                ))

        return matches

    def _get_context(self, line: str, start: int, end: int, context_chars: int = 50) -> str:
        """Get surrounding context for a match"""
        # Get text before and after the match
        before = line[max(0, start - context_chars):start]
        matched = line[start:end]
        after = line[end:min(len(line), end + context_chars)]

        # Clean up and format
        context = f"...{before}**{matched}**{after}..."
        return context.strip()
