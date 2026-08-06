"""
Role Suggester
Proposes what part a discovered person plays — teacher, paediatrician, carer —
from the text around their name, and reports the evidence for it.

Proposes, never assumes. A wrong role is worse than no role: labelling a
paediatrician [Teacher] invites an AI to read clinical advice as classroom
observation. With no quotable evidence the answer is 'unknown', which the
caller turns into [Other person] and puts in front of the user to decide.
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from pseudonym_map import DEFAULT_ROLE


# Keywords are matched whole-word. Short ones ('ot', 'gp') would otherwise fire
# inside ordinary words — "note", "gpa" — and manual space-padding is worse
# still, because it misses a keyword at the very start or end of a snippet
# ("OT recommended weekly sessions").
ROLE_KEYWORDS: Dict[str, List[str]] = {
    # 'guardian' appears under BOTH parent and carer on purpose. Australian
    # school forms say "Parent/Guardian", so the word genuinely supports either
    # reading; the tie resolves to 'unknown' and the user decides. That is the
    # ambiguous case this whole feature exists for.
    'parent': ['mother', 'mum', 'mom', 'father', 'dad', 'parent', 'guardian',
               'stepmother', 'stepfather', 'step-mother', 'step-father'],
    'carer': ['carer', 'caregiver', 'foster', 'kinship', 'guardian'],
    'teacher': ['teacher', 'classroom teacher', 'class teacher', 'tutor'],
    'school_staff': ['principal', 'deputy', 'assistant principal', 'aide', 'sso',
                     'wellbeing', 'coordinator', 'integration aide', 'chaplain',
                     'counsellor', 'counselor', 'learning support officer'],
    'health': ['paediatrician', 'pediatrician', 'psychologist', 'psychiatrist',
               'speech', 'pathologist', 'occupational therapist', 'ot',
               'physiotherapist', 'physio', 'gp', 'doctor', 'clinician',
               'therapist', 'audiologist', 'optometrist'],
    'support_worker': ['ndis', 'support worker', 'social worker', 'case manager',
                       'caseworker', 'case worker', 'advocate',
                       'support coordinator'],
    # The bare word 'student' is deliberately absent: it is near-ubiquitous in
    # these reports and almost always means the report's subject, who is never
    # in this list. A lone "student" beside a teacher's name would mislabel them
    # a classmate. Only qualifying phrases count.
    'other_student': ['classmate', 'peer', 'fellow student', 'another student',
                      'sibling', 'brother', 'sister'],
}

# An honorific on the name itself is weak evidence — enough to propose, not
# enough to call likely.
_DOCTOR_HONORIFIC = re.compile(r"^\s*(dr|doctor)\b\.?", re.IGNORECASE)

_CONF_LIKELY = 'likely'
_CONF_POSSIBLE = 'possible'
_CONF_UNKNOWN = 'unknown'


@dataclass
class RoleSuggestion:
    """A proposed role and the reason for it, for the user to confirm."""
    role_key: str
    confidence: str          # 'likely' | 'possible' | 'unknown'
    evidence: str            # the phrase found; '' when unknown
    snippet: str             # the context it came from, for display


def _compile(keyword: str) -> 're.Pattern':
    return re.compile(r'(?<![A-Za-z0-9])' + re.escape(keyword)
                      + r'(?![A-Za-z0-9])', re.IGNORECASE)


_PATTERNS = {
    role: [(kw, _compile(kw)) for kw in sorted(keywords, key=len, reverse=True)]
    for role, keywords in ROLE_KEYWORDS.items()
}


def suggest_role(name: str, contexts: List[str]) -> RoleSuggestion:
    """
    Propose a role for `name` from the text around its occurrences.

    Args:
        name: the person's name as detected.
        contexts: snippets of text each occurrence appeared in.

    Returns:
        A RoleSuggestion. 'unknown' whenever the evidence does not point to
        exactly one role — including when two roles tie, which is what happens
        for a word like "guardian" that genuinely belongs to two of them.
    """
    hits: Dict[str, List[tuple]] = {}

    for snippet in contexts or []:
        if not snippet:
            continue
        for role, patterns in _PATTERNS.items():
            for keyword, pattern in patterns:
                if pattern.search(snippet):
                    hits.setdefault(role, []).append((keyword, snippet))
                    break  # longest keyword for this role already won

    if hits:
        ranked = sorted(hits.items(), key=lambda kv: len(kv[1]), reverse=True)
        if len(ranked) == 1 or len(ranked[0][1]) > len(ranked[1][1]):
            role = ranked[0][0]
            keyword, snippet = ranked[0][1][0]
            return RoleSuggestion(role, _CONF_LIKELY, keyword, snippet.strip())
        # A tie means the text genuinely supports two readings — ask the user
        # rather than pick one and sound confident about it.
        return RoleSuggestion(DEFAULT_ROLE, _CONF_UNKNOWN, '', '')

    if _DOCTOR_HONORIFIC.match(name or ''):
        return RoleSuggestion('health', _CONF_POSSIBLE, 'Dr', (name or '').strip())

    return RoleSuggestion(DEFAULT_ROLE, _CONF_UNKNOWN, '', '')
