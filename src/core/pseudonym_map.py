"""
Pseudonym Map
Builds privacy-safe replacement labels for de-identification mode.

The governing rule: a label must never carry information derived from the real
name. "Billy Bob" becomes [Student], never [Student(BB)] — initials are barely
pseudonymous in a small school community. Labels are role + sequence number
only, and the real names live solely in the run's key file.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from pii_detector import generate_name_variations


# Structured PII maps straight to a generic token: once the value is gone there
# is no identity left to number.
CATEGORY_LABELS = {
    'Phone number': '[phone]',
    'Email address': '[email]',
    'Address': '[address]',
    'Date of birth': '[date of birth]',
    'Medicare number': '[Medicare number]',
    'Student ID': '[student ID]',
    'Centrelink CRN': '[Centrelink CRN]',
    'NDIS number': '[NDIS number]',
    'ABN': '[ABN]',
    'Passport number': '[passport number]',
    'Location (NER)': '[location]',
    'Date/Time (NER)': '[date]',
}

STUDENT_LABEL = '[Student]'
SHARED_SURNAME_LABEL = '[Family name]'
FALLBACK_NAME_LABEL = '[name]'
FALLBACK_LABEL = '[redacted]'

# Owner priority. When a given name is shared by several people, the bare first
# name resolves to the highest-priority claimant — a lone first name in a school
# report overwhelmingly means the subject student.
_PRIORITY_STUDENT = 0
_PRIORITY_PARENT = 1
_PRIORITY_FAMILY = 2
_PRIORITY_ORG = 3
_PRIORITY_PERSON = 4

# Words that must not become standalone organisation variations. Mirrors the
# generic-word filter in PIIDetector._detect_organisation_names.
_ORG_GENERIC_WORDS = {
    'school', 'primary', 'secondary', 'college', 'clinic',
    'centre', 'center', 'hospital', 'practice', 'academy',
    'institute', 'university', 'department', 'service',
    'services', 'psychology', 'medical', 'health', 'group',
    'the', 'and', 'for', 'inc', 'ltd', 'pty',
}

_POSSESSIVE_RE = re.compile(r"['’]s$")

_HONORIFICS = {'mr', 'mrs', 'ms', 'miss', 'mx', 'dr', 'doctor',
               'prof', 'professor', 'sir', 'madam'}

# Words that mean a candidate is a form label or a run-together extraction span,
# not a person. Chosen to avoid plausible Australian surnames.
_NOT_A_PERSON_TOKEN = {
    'email', 'phone', 'mobile', 'telephone', 'address', 'date', 'birth', 'dob',
    'medicare', 'crn', 'ndis', 'abn', 'passport', 'number', 'details',
    'signature', 'contact', 'guardian', 'parent', 'student', 'teacher',
    'school', 'report', 'term', 'information', 'assessment',
}


def _norm(text: str) -> str:
    """Casefold and collapse whitespace so variations compare reliably."""
    return ' '.join(str(text).lower().split())


def clean_person_name(raw: str):
    """
    Normalise a candidate person name, or return None if it isn't one.

    PDF text extraction routinely hands NER a run-together span like
    "Billy Bob        Date of Birth", and form labels like "Email" get picked up
    as names. Registering those as people invents bogus [Person N] entries and —
    worse — makes the same child two different labels on two different lines.

    Leading honorifics are stripped so "Ms Williams" resolves to the same person
    as "Sarah Williams" rather than becoming a second teacher.
    """
    tokens = ' '.join((raw or '').split()).split()
    while tokens and tokens[0].lower().rstrip('.') in _HONORIFICS:
        tokens = tokens[1:]
    if not tokens or len(tokens) > 4:
        return None
    for token in tokens:
        core = token.strip(".'’-")
        if not core:
            return None
        if not core.replace("'", '').replace('’', '').replace('-', '').isalpha():
            return None
        if core.lower() in _NOT_A_PERSON_TOKEN:
            return None
    return ' '.join(tokens)


def _name_fullness(name: str):
    """
    How complete a written form of a name is, for choosing the one to show in
    the key file. More words wins; ties go to whichever spells more of them out,
    so "Sarah Williams" beats "S. Williams".
    """
    tokens = name.split()
    spelled_out = sum(1 for t in tokens if len(t.strip(".'’-")) > 1)
    return (len(tokens), spelled_out)


def _contains_phrase(tokens, phrase_tokens) -> bool:
    """Whether phrase_tokens appears as a whole-word run inside tokens."""
    n = len(phrase_tokens)
    if not n or n > len(tokens):
        return False
    return any(tokens[i:i + n] == phrase_tokens for i in range(len(tokens) - n + 1))


def is_person_category(category: str) -> bool:
    """
    Whether a PII category describes a person (as opposed to an organisation or
    a structured value). Used to decide which matches get registered as people.

    Deliberately a heuristic over exact strings: detection categories are added
    over time, and a new person category defaulting to 'person' is the safe
    failure mode.
    """
    cl = (category or '').lower()
    if 'organisation' in cl or 'organization' in cl:
        return False
    return any(hint in cl for hint in ('name', 'person', 'parent', 'family'))


@dataclass
class _Owner:
    """A real person or organisation and the label standing in for them."""
    label: str
    full_name: str
    priority: int
    seq: int
    is_org: bool = False
    variations: Set[str] = field(default_factory=set)
    surname: Optional[str] = None


class PseudonymMap:
    """
    Maps every known name variation to a non-identifying label.

    Two names are the same person only when their full names match or one is a
    recognised short form of the other. Sharing a single token is NOT identity:
    classmate "Billy Chen" must not be absorbed into student "Billy Bob" just
    because they share a first name, or the AI reading the output would
    attribute one child's behaviour to the other.
    """

    def __init__(
        self,
        student_name: str = '',
        parent_names: List[str] = None,
        family_names: List[str] = None,
        organisation_names: List[str] = None,
    ):
        self._owners: List[_Owner] = []
        self._seq = 0
        self._person_counter = 0
        # variation (normalised) -> [(owner_index, kind)], kind in {'surname','other'}
        self._claims: Dict[str, List[Tuple[int, str]]] = {}
        self._variation_labels: Dict[str, str] = {}

        if student_name and student_name.strip():
            self._add_person(student_name, STUDENT_LABEL, _PRIORITY_STUDENT,
                             include_nicknames=True)

        for i, name in enumerate(self._clean(parent_names), start=1):
            self._add_person(name, f'[Parent {i}]', _PRIORITY_PARENT)

        for i, name in enumerate(self._clean(family_names), start=1):
            self._add_person(name, f'[Family member {i}]', _PRIORITY_FAMILY)

        for i, name in enumerate(self._clean(organisation_names), start=1):
            self._add_org(name, f'[Organisation {i}]')

        self._rebuild()

    # ── Construction ─────────────────────────────────────────────────────

    @staticmethod
    def _clean(names: Optional[List[str]]) -> List[str]:
        return [n.strip() for n in (names or []) if n and n.strip()]

    def _add_person(self, full_name: str, label: str, priority: int,
                    include_nicknames: bool = False) -> _Owner:
        variations, nicknames = generate_name_variations(
            full_name, include_nicknames=include_nicknames
        )
        parts = full_name.split()
        surname = _norm(parts[-1]) if len(parts) >= 2 else None

        owner = _Owner(
            label=label, full_name=full_name, priority=priority,
            seq=self._seq, surname=surname,
        )
        self._seq += 1
        self._owners.append(owner)
        index = len(self._owners) - 1

        for var in list(variations) + list(nicknames):
            key = _norm(var)
            if not key:
                continue
            owner.variations.add(key)
            kind = 'surname' if (surname and key == surname) else 'other'
            self._claims.setdefault(key, []).append((index, kind))
        # The exact entered name always maps, even if shorter than the
        # variation filter's 3-character floor (students named "Jo").
        owner.variations.add(_norm(full_name))
        return owner

    def _add_org(self, org_name: str, label: str) -> _Owner:
        owner = _Owner(
            label=label, full_name=org_name, priority=_PRIORITY_ORG,
            seq=self._seq, is_org=True,
        )
        self._seq += 1
        self._owners.append(owner)
        index = len(self._owners) - 1

        candidates = [org_name]
        candidates.extend(
            w for w in org_name.split()
            if len(w) >= 3 and w.lower() not in _ORG_GENERIC_WORDS
        )
        for var in candidates:
            key = _norm(var)
            if not key:
                continue
            owner.variations.add(key)
            self._claims.setdefault(key, []).append((index, 'other'))
        return owner

    def _rebuild(self) -> None:
        """Resolve every claimed variation to a single label."""
        resolved: Dict[str, str] = {}
        for key, claims in self._claims.items():
            if len(claims) == 1:
                resolved[key] = self._owners[claims[0][0]].label
                continue
            distinct = {idx for idx, _ in claims}
            if len(distinct) == 1:
                resolved[key] = self._owners[claims[0][0]].label
                continue
            # Shared by several people. A surname shared by everyone who claims
            # it is genuinely ambiguous — neither safe nor honest to guess.
            if all(kind == 'surname' for _, kind in claims):
                resolved[key] = SHARED_SURNAME_LABEL
            else:
                owners = sorted(
                    (self._owners[idx] for idx in distinct),
                    key=lambda o: (o.priority, o.seq),
                )
                resolved[key] = owners[0].label
        self._variation_labels = resolved

    # ── Registration ─────────────────────────────────────────────────────

    def register_person(self, full_name: str) -> str:
        """
        Return the label for a person discovered during detection, minting a new
        [Person N] only when they are genuinely someone new.

        Merges when the full names match or one full name is a recognised short
        form of the other ("S. Williams" is "Sarah Williams"). A single-token
        candidate that matches several owners resolves to the highest-priority
        one. A shared token alone never merges two identities.
        """
        full_name = clean_person_name(full_name)
        if not full_name:
            # Not a person — a form label or an extraction span. label_for()
            # still resolves it, from whichever real name it contains.
            return FALLBACK_NAME_LABEL

        norm = _norm(full_name)
        cand_variations, _ = generate_name_variations(full_name, include_nicknames=False)
        cand_norms = {_norm(v) for v in cand_variations if v.strip()}
        cand_norms.add(norm)

        matched = [
            (index, owner) for index, owner in enumerate(self._owners)
            if not owner.is_org
            and (norm in owner.variations or _norm(owner.full_name) in cand_norms)
        ]
        if matched:
            matched.sort(key=lambda pair: (pair[1].priority, pair[1].seq))
            index, owner = matched[0]

            # Record the surface forms this candidate introduces. Without this,
            # a merge is forgotten the moment it returns: registering
            # "S. Williams" then "Sarah Williams" merges correctly, but
            # "Sarah W." is then unrecognised and mints a SECOND [Person N] for
            # the same human — two labels for one person, and two rows in the
            # key file. Only genuinely new forms are claimed; a form someone
            # else already claims keeps its existing resolution, or adding it
            # here would quietly break the shared-surname rule.
            for variation in cand_norms:
                if variation and variation not in self._claims:
                    owner.variations.add(variation)
                    kind = ('surname' if owner.surname and variation == owner.surname
                            else 'other')
                    self._claims[variation] = [(index, kind)]

            # Prefer the fullest form as the display name, so the key file says
            # "Sarah Williams" rather than whichever abbreviation appeared first.
            if _name_fullness(full_name) > _name_fullness(owner.full_name):
                owner.full_name = full_name

            self._rebuild()
            return owner.label

        self._person_counter += 1
        self._add_person(full_name, f'[Person {self._person_counter}]', _PRIORITY_PERSON)
        self._rebuild()
        return self._variation_labels.get(norm, f'[Person {self._person_counter}]')

    # ── Lookup ───────────────────────────────────────────────────────────

    def label_for(self, match_text: str, category: str = '') -> str:
        """Label to substitute for one detected PII string."""
        key = _POSSESSIVE_RE.sub('', _norm(match_text))
        if key in self._variation_labels:
            return self._variation_labels[key]
        if category in CATEGORY_LABELS:
            return CATEGORY_LABELS[category]
        cl = (category or '').lower()
        if 'organisation' in cl or 'organization' in cl:
            return '[organisation]'
        if is_person_category(category):
            # An extraction span like "Billy Bob        Date of Birth" is still
            # the student — resolve it from the longest real name inside it, so
            # one child does not end up with two labels in the same document.
            contained = self._label_from_contained(key)
            if contained:
                return contained
            return FALLBACK_NAME_LABEL
        return FALLBACK_LABEL

    def _label_from_contained(self, key: str):
        """Label of the longest known variation appearing inside `key`."""
        tokens = key.split()
        if len(tokens) < 2:
            return None
        best_len, best_label = 0, None
        for variation, label in self._variation_labels.items():
            phrase = variation.split()
            if len(phrase) > best_len and _contains_phrase(tokens, phrase):
                best_len, best_label = len(phrase), label
        return best_label

    def all_labels(self) -> Set[str]:
        """Every label this map can emit — used to guard against re-matching."""
        labels = {o.label for o in self._owners}
        labels.update(CATEGORY_LABELS.values())
        labels.update({SHARED_SURNAME_LABEL, FALLBACK_NAME_LABEL,
                       FALLBACK_LABEL, '[organisation]'})
        return labels

    def key_entries(self) -> List[Tuple[str, str]]:
        """(label, real name) pairs for the key file, in discovery order."""
        return [(o.label, o.full_name)
                for o in sorted(self._owners, key=lambda o: o.seq)]

    def ambiguity_notes(self) -> List[str]:
        """
        Plain-English notes on every name shared by more than one person, so the
        teacher can sanity-check how the AI read the de-identified text.
        """
        notes = []
        for key, claims in sorted(self._claims.items()):
            distinct = sorted({idx for idx, _ in claims})
            if len(distinct) < 2:
                continue
            label = self._variation_labels.get(key, '')
            others = ', '.join(
                f'"{self._owners[i].full_name}" {self._owners[i].label}'
                for i in distinct
            )
            notes.append(
                f'"{key}" is shared by {others} — on its own it was labelled {label}.'
            )
        return notes
