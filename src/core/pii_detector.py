"""
PII Detection Engine
Detects personally identifiable information using regex patterns and contextual rules.
"""

import re
import unicodedata
from typing import List, Dict, Tuple
from dataclasses import dataclass
from nickname_map import NICKNAME_MAP, REVERSE_NICKNAME_MAP


def _normalise_text(text: str) -> str:
    """NFKC normalise and replace smart quotes with ASCII equivalents."""
    text = unicodedata.normalize('NFKC', text)
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    text = text.replace('\u201C', '"').replace('\u201D', '"')
    return text

@dataclass
class PIIMatch:
    """Represents a detected PII item"""
    text: str
    category: str
    confidence: float  # 0.0 to 1.0
    page_num: int
    line_num: int
    context: str  # Surrounding text for display
    source: str = 'regex'  # Detection source: 'regex', 'presidio', 'gliner'
    bbox: Tuple[float, float, float, float] = None  # Bounding box coordinates (x0, y0, x1, y1)

    @property
    def confidence_label(self) -> str:
        """Map numeric confidence to display label"""
        if self.confidence >= 0.8:
            return 'high'
        elif self.confidence >= 0.5:
            return 'medium'
        else:
            return 'low'


# Words that must never be extracted as a person name from contextual detection.
# Stored at module level for O(1) lookup on every match.
_CONTEXTUAL_NAME_EXCLUDE = {
    # Titles
    'dr', 'mr', 'mrs', 'ms', 'miss',
    # Family relationship words — these are roles, not names
    'dad', 'mum', 'mom', 'mother', 'father',
    'brother', 'sister', 'sibling',
    'guardian', 'parent', 'partner', 'carer', 'caregiver',
    'nan', 'nana', 'grandmother', 'grandfather', 'grandma', 'grandpa',
    # Articles, prepositions
    'the', 'and', 'or', 'of', 'in', 'on', 'at', 'to', 'for',
    'with', 'from', 'by', 'as',
    # Auxiliary verbs
    'is', 'are', 'was', 'were', 'been', 'be',
    'have', 'has', 'had', 'do', 'does', 'did',
    'will', 'would', 'should', 'can', 'could',
    'may', 'might', 'must', 'shall',
    # Common English words that are also nicknames (false positive risk)
    'art', 'max', 'don', 'pat', 'ray', 'ted', 'rob', 'bob',
    'rick', 'dick', 'rich', 'bill', 'sue', 'reg', 'ron', 'len',
    'belle', 'penny', 'cam', 'con', 'cal', 'gen', 'dom',
}


def generate_name_variations(name: str, preserve_short_name: str = None,
                             include_nicknames: bool = False) -> tuple:
    """Generate name variations for detection. Standalone version for use by orchestrator.

    Returns:
        Tuple of (variations_list, nickname_list). nickname_list is empty unless
        include_nicknames=True.
    """
    name = name.strip()
    if not name:
        return [], []
    parts = name.split()
    variations = [name]
    if len(parts) >= 2:
        first, last = parts[0], parts[-1]
        variations.append(first)
        variations.append(last)
        variations.append(f"{first[0]}. {last}")
        variations.append(f"{first} {last[0]}.")
        variations.append(f"{first[0]}.{last[0]}.")
        # Full initials string (e.g. "JS" for "Jane Smith")
        initials = ''.join(p[0] for p in parts)
        if len(initials) >= 3:
            variations.append(initials)

    # Nickname expansion
    nickname_vars = []
    if include_nicknames:
        for part in parts:
            part_lower = part.lower()
            # Formal -> nicknames
            if part_lower in NICKNAME_MAP:
                nickname_vars.extend(NICKNAME_MAP[part_lower])
            # Nickname -> formal names
            if part_lower in REVERSE_NICKNAME_MAP:
                nickname_vars.extend(REVERSE_NICKNAME_MAP[part_lower])

    # Filter main variations
    preserve = preserve_short_name or name
    variations = [v for v in variations if len(v) >= 3 or v == preserve]
    variations = list(dict.fromkeys(v.strip() for v in variations if v.strip()))

    # Filter nicknames: min 3 chars and not a common word
    filtered_nicks = []
    if include_nicknames and nickname_vars:
        filtered_nicks = [n for n in set(nickname_vars)
                          if len(n) >= 3 and n.lower() not in _CONTEXTUAL_NAME_EXCLUDE]
    return variations, filtered_nicks


class PIIDetector:
    """Detects PII in text using pattern matching and contextual analysis"""

    # Australian phone number patterns
    PHONE_PATTERNS = [
        r'\+61[\s\-]*[2-478][\s\-]*\d{4}[\s\-]*\d{4}',  # +61 2 1234 5678
        r'0[2-478][\s\-]*\d{4}[\s\-]*\d{4}',  # 02 1234 5678
        r'\(0[2-478]\)[\s\-]*\d{4}[\s\-]*\d{4}',  # (02) 1234 5678
        r'04\d{2}[\s\-]*\d{3}[\s\-]*\d{3}',  # 0412 345 678 or 0412-345-678
        r'04\d{8}',  # 0412345678
    ]

    # Email pattern
    EMAIL_PATTERN = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

    # Australian address pattern
    ADDRESS_PATTERN = r'\d+\s+[A-Za-z\s]+(?:Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Court|Ct|Place|Pl|Lane|Ln|Way|Crescent|Cres|Boulevard|Blvd|Terrace|Tce|Close|Cl|Grove|Gr|Highway|Hwy|Parade|Pde|Circuit|Cct|Loop|Rise|Vale|Mews|Esplanade|Esp),?\s+[A-Za-z\s]+,?\s+(?:VIC|NSW|QLD|SA|WA|TAS|NT|ACT|Victoria|New South Wales|Queensland|South Australia|Western Australia|Tasmania|Northern Territory|Australian Capital Territory)\s+\d{4}'

    # Medicare number pattern
    MEDICARE_PATTERN = r'\b\d{4}\s?\d{5}\s?\d\b'

    # Centrelink CRN pattern
    CRN_PATTERN = r'\b[A-Z0-9]{9}\b'

    # Student ID pattern (3 uppercase letters + digits)
    STUDENT_ID_PATTERN = r'\b[A-Z]{3}\d{3,}\b'

    # NDIS participant number (9 digits, requires keyword)
    NDIS_PATTERN = r'(?i)(?:ndis|participant)\s*(?:number|no\.?|#)?\s*:?\s*(\d{9})\b'

    # Australian Business Number (11 digits, requires keyword)
    ABN_PATTERN = r'(?i)abn\s*:?\s*(\d{2}\s?\d{3}\s?\d{3}\s?\d{3})\b'

    # Passport number (requires keyword)
    PASSPORT_PATTERN = r'(?i)passport\s*(?:number|no\.?|#)?\s*:?\s*([A-Z]\d{7})\b'

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
        r'Partner',
        r'Family member',
        r'Lives with',
        r'Referred by parent',
        r'Parent/Guardian signature',
        r'Stepmother', r'Stepfather', r'Foster\s+parent', r'Foster\s+carer',
        r'Legal\s+guardian', r'Primary\s+carer', r'Kinship\s+carer',
        r'Aunt', r'Uncle', r'Grandparent', r'Grandmother', r'Grandfather',
    ]

    def __init__(self, student_name: str, parent_names: List[str] = None, family_names: List[str] = None, organisation_names: List[str] = None):
        """
        Initialize the PII detector

        Args:
            student_name: Full name of the student
            parent_names: List of parent/guardian names
            family_names: List of other family member names
            organisation_names: List of organisation/school names to detect
        """
        self.student_name = student_name.strip()
        self.parent_names = [n.strip() for n in (parent_names or [])]
        self.family_names = [n.strip() for n in (family_names or [])]
        self.organisation_names = [n.strip() for n in (organisation_names or [])]

        # Generate name variations
        self.name_variations = self._generate_name_variations()

    def _generate_name_variations(self) -> List[str]:
        """Generate variations of the student name (first, last, initials, etc.)"""
        main_vars, self._nickname_variations = generate_name_variations(
            self.student_name,
            preserve_short_name=self.student_name,
            include_nicknames=True
        )
        return main_vars

    @staticmethod
    def _peek_next_line(lines: list, line_idx: int) -> str:
        """Return the next line if it exists, else empty string."""
        if line_idx + 1 < len(lines):
            return lines[line_idx + 1]
        return ""

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

        # Normalise input text (handles smart quotes, ligatures, NFKC decomposition)
        text = _normalise_text(text)

        lines = text.split('\n')
        for line_idx, line in enumerate(lines):
            line_num = line_idx + 1
            # Detect student name and variations
            matches.extend(self._detect_names(line, page_num, line_num))

            # Detect phone numbers
            matches.extend(self._detect_phones(line, page_num, line_num))

            # Detect emails
            matches.extend(self._detect_emails(line, page_num, line_num))

            # Detect addresses
            matches.extend(self._detect_addresses(line, page_num, line_num, lines, line_idx))

            # Detect Medicare numbers
            matches.extend(self._detect_medicare(line, page_num, line_num, lines, line_idx))

            # Detect CRN
            matches.extend(self._detect_crn(line, page_num, line_num, lines, line_idx))

            # Detect student IDs
            matches.extend(self._detect_student_id(line, page_num, line_num))

            # Detect DOB (context-sensitive)
            matches.extend(self._detect_dob(line, page_num, line_num, lines, line_idx))

            # Detect contextual family names
            matches.extend(self._detect_contextual_names(line, page_num, line_num, lines, line_idx))

            # Detect organisation names
            matches.extend(self._detect_organisation_names(line, page_num, line_num))

            # Detect NDIS, ABN, passport numbers
            matches.extend(self._detect_ndis(line, page_num, line_num))
            matches.extend(self._detect_abn(line, page_num, line_num))
            matches.extend(self._detect_passport(line, page_num, line_num))

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
                    confidence=0.95,
                    page_num=page_num,
                    line_num=line_num,
                    context=context
                ))

        # Nickname variations at lower confidence
        for nick in getattr(self, '_nickname_variations', []):
            pattern = re.compile(r'\b' + re.escape(nick) + r'\b', re.IGNORECASE)
            for m in pattern.finditer(line):
                matches.append(PIIMatch(
                    text=m.group(), category="Student name (nickname)", confidence=0.75,
                    page_num=page_num, line_num=line_num,
                    context=self._get_context(line, m.start(), m.end())
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
                    confidence=0.95,
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
                confidence=0.95,
                page_num=page_num,
                line_num=line_num,
                context=context
            ))
        return matches

    def _detect_addresses(self, line: str, page_num: int, line_num: int, lines=None, line_idx=None) -> List[PIIMatch]:
        """Detect Australian addresses"""
        matches = []
        pattern = re.compile(self.ADDRESS_PATTERN, re.IGNORECASE)
        for match in pattern.finditer(line):
            context = self._get_context(line, match.start(), match.end())
            matches.append(PIIMatch(
                text=match.group(),
                category='Address',
                confidence=0.95,
                page_num=page_num,
                line_num=line_num,
                context=context
            ))
        return matches

    def _detect_medicare(self, line: str, page_num: int, line_num: int, lines=None, line_idx=None) -> List[PIIMatch]:
        """Detect Medicare numbers"""
        matches = []
        if 'medicare' not in line.lower():
            return matches
        pattern = re.compile(self.MEDICARE_PATTERN)
        for match in pattern.finditer(line):
            context = self._get_context(line, match.start(), match.end())
            matches.append(PIIMatch(
                text=match.group(),
                category='Medicare number',
                confidence=0.95,
                page_num=page_num,
                line_num=line_num,
                context=context
            ))
        # Cross-line: keyword found but no number on this line
        if not matches and lines is not None and line_idx is not None:
            next_line = self._peek_next_line(lines, line_idx)
            if next_line:
                for m in re.finditer(self.MEDICARE_PATTERN, next_line):
                    matches.append(PIIMatch(
                        text=m.group(), category="Medicare number", confidence=0.90,
                        page_num=page_num, line_num=line_num + 1,
                        context=self._get_context(next_line, m.start(), m.end())
                    ))
        return matches

    def _detect_crn(self, line: str, page_num: int, line_num: int, lines=None, line_idx=None) -> List[PIIMatch]:
        """Detect Centrelink CRN"""
        matches = []
        has_keyword = 'CRN' in line.upper()
        if has_keyword:
            pattern = re.compile(self.CRN_PATTERN)
            for match in pattern.finditer(line):
                context = self._get_context(line, match.start(), match.end())
                matches.append(PIIMatch(
                    text=match.group(),
                    category='Centrelink CRN',
                    confidence=0.65,
                    page_num=page_num,
                    line_num=line_num,
                    context=context
                ))
            # Cross-line: keyword found but no CRN token on this line
            if not matches and lines is not None and line_idx is not None:
                next_line = self._peek_next_line(lines, line_idx)
                if next_line:
                    for m in re.finditer(self.CRN_PATTERN, next_line):
                        matches.append(PIIMatch(
                            text=m.group(), category="Centrelink CRN", confidence=0.60,
                            page_num=page_num, line_num=line_num + 1,
                            context=self._get_context(next_line, m.start(), m.end())
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

            confidence = 0.95 if id_text[:3] == surname_prefix else 0.65
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

    def _detect_dob(self, line: str, page_num: int, line_num: int, lines=None, line_idx=None) -> List[PIIMatch]:
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
                        confidence=0.95,
                        page_num=page_num,
                        line_num=line_num,
                        context=context
                    ))

            # Cross-line: label found but no date on this line — peek at next line
            if not matches and lines is not None and line_idx is not None:
                next_line = self._peek_next_line(lines, line_idx)
                if next_line:
                    for date_pattern in self.DATE_PATTERNS:
                        for m in re.finditer(date_pattern, next_line):
                            matches.append(PIIMatch(
                                text=m.group(), category="Date of birth", confidence=0.90,
                                page_num=page_num, line_num=line_num + 1,
                                context=self._get_context(next_line, m.start(), m.end())
                            ))
        return matches

    def _detect_ndis(self, line: str, page_num: int, line_num: int) -> List[PIIMatch]:
        """Detect NDIS participant numbers (9 digits with keyword)."""
        matches = []
        for m in re.finditer(self.NDIS_PATTERN, line):
            matches.append(PIIMatch(
                text=m.group(1), category="NDIS number", confidence=0.90,
                page_num=page_num, line_num=line_num,
                context=self._get_context(line, m.start(), m.end())
            ))
        return matches

    def _detect_abn(self, line: str, page_num: int, line_num: int) -> List[PIIMatch]:
        """Detect Australian Business Numbers (11 digits with keyword)."""
        matches = []
        for m in re.finditer(self.ABN_PATTERN, line):
            matches.append(PIIMatch(
                text=m.group(1), category="ABN", confidence=0.90,
                page_num=page_num, line_num=line_num,
                context=self._get_context(line, m.start(), m.end())
            ))
        return matches

    def _detect_passport(self, line: str, page_num: int, line_num: int) -> List[PIIMatch]:
        """Detect passport numbers (letter + 7 digits with keyword)."""
        matches = []
        for m in re.finditer(self.PASSPORT_PATTERN, line):
            matches.append(PIIMatch(
                text=m.group(1), category="Passport number", confidence=0.65,
                page_num=page_num, line_num=line_num,
                context=self._get_context(line, m.start(), m.end())
            ))
        return matches

    def _detect_contextual_names(self, line: str, page_num: int, line_num: int, lines=None, line_idx=None) -> List[PIIMatch]:
        """Detect names appearing after contextual keywords"""
        matches = []

        # Check for family keywords
        for keyword in self.FAMILY_KEYWORDS:
            category = 'Parent/Guardian' if any(k in keyword.lower() for k in ['mother', 'father', 'parent', 'mum', 'dad', 'guardian', 'carer', 'partner']) else 'Family member'

            # Name capture pattern: 1-2 capitalised words (or ALL-CAPS words)
            _name_pat = r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?|[A-Z]{2,}(?:\s+[A-Z]{2,})?)'

            # Three syntactic patterns for how documents reference family members:
            #   1. "Father: Nick" or "Father Nick"  (colon/space)
            #   2. "his father (Nick)"               (parenthetical)
            #   3. "his sister, Summer,"              (comma-separated)
            patterns = [
                re.compile(r'\b' + keyword + r'[:\s]+' + _name_pat, re.IGNORECASE),
                re.compile(r'\b' + keyword + r'\s*\(\s*' + _name_pat + r'\s*\)', re.IGNORECASE),
                re.compile(r'\b' + keyword + r',\s+' + _name_pat, re.IGNORECASE),
            ]

            found_name = False
            for pattern in patterns:
                for match in pattern.finditer(line):
                    name = match.group(1)
                    # Skip common words, articles, prepositions, and professional titles
                    if name.lower() not in _CONTEXTUAL_NAME_EXCLUDE:
                        found_name = True
                        context = self._get_context(line, match.start(1), match.end(1))
                        matches.append(PIIMatch(
                            text=name,
                            category=category,
                            confidence=0.65,
                            page_num=page_num,
                            line_num=line_num,
                            context=context
                        ))

            # Cross-line: keyword matched but no name captured on this line
            if not found_name and lines is not None and line_idx is not None:
                keyword_pat = re.compile(r'\b' + keyword + r'\b', re.IGNORECASE)
                if keyword_pat.search(line):
                    next_line = self._peek_next_line(lines, line_idx)
                    if next_line:
                        name_only = re.compile(r'^' + _name_pat)
                        m = name_only.match(next_line.strip())
                        if m and m.group(1).lower() not in _CONTEXTUAL_NAME_EXCLUDE:
                            matches.append(PIIMatch(
                                text=m.group(1), category=category,
                                confidence=0.60, page_num=page_num,
                                line_num=line_num + 1,
                                context=next_line.strip()[:80]
                            ))

        # Also check user-provided parent/family names
        for parent_name in self.parent_names:
            pattern = re.compile(r'\b' + re.escape(parent_name) + r'\b', re.IGNORECASE)
            for match in pattern.finditer(line):
                context = self._get_context(line, match.start(), match.end())
                matches.append(PIIMatch(
                    text=match.group(),
                    category='Parent/Guardian (user-provided)',
                    confidence=0.95,
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
                    confidence=0.95,
                    page_num=page_num,
                    line_num=line_num,
                    context=context
                ))

        return matches

    def _detect_organisation_names(self, line: str, page_num: int, line_num: int) -> List[PIIMatch]:
        """Detect user-provided organisation names and their significant words."""
        matches = []

        # Generic words that should NOT become standalone variations
        _ORG_GENERIC_WORDS = {
            'school', 'primary', 'secondary', 'college', 'clinic',
            'centre', 'center', 'hospital', 'practice', 'academy',
            'institute', 'university', 'department', 'service',
            'services', 'psychology', 'medical', 'health', 'group',
            'the', 'and', 'for', 'inc', 'ltd', 'pty',
        }

        for org_name in self.organisation_names:
            # Full org name match
            pattern = re.compile(r'\b' + re.escape(org_name) + r'\b', re.IGNORECASE)
            for match in pattern.finditer(line):
                context = self._get_context(line, match.start(), match.end())
                matches.append(PIIMatch(
                    text=match.group(),
                    category='Organisation name',
                    confidence=0.95,
                    page_num=page_num,
                    line_num=line_num,
                    context=context,
                    source='regex',
                ))

            # Individual word variations (3+ chars, skip common/generic words)
            for word in org_name.split():
                clean_word = word.strip("''\u2019")
                if len(clean_word) < 3:
                    continue
                if clean_word.lower() in _CONTEXTUAL_NAME_EXCLUDE:
                    continue
                if clean_word.lower() in _ORG_GENERIC_WORDS:
                    continue
                word_pattern = re.compile(r'\b' + re.escape(clean_word) + r'\b', re.IGNORECASE)
                for match in word_pattern.finditer(line):
                    context = self._get_context(line, match.start(), match.end())
                    matches.append(PIIMatch(
                        text=match.group(),
                        category='Organisation name',
                        confidence=0.95,
                        page_num=page_num,
                        line_num=line_num,
                        context=context,
                        source='regex',
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
