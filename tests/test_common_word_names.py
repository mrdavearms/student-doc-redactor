"""
Names that are also ordinary English words ("Will", "Young", "Grace", "Long")
match only when they are not written entirely in lowercase (rule 7a).

A student called William Young used to have every "young" in the report
offered, and because a selected string is redacted on every page (rule 11a),
unticking those rows changed nothing.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

from case_rules import NOT_LOWERCASE, case_mode
from common_words import COMMON_WORDS
from pii_orchestrator import PIIOrchestrator


def _texts(matches):
    return sorted(m.text for m in matches)


class TestShippedWordList:

    def test_the_names_this_work_is_for_are_on_it(self):
        for name in ['Will', 'Young', 'Grace', 'Long', 'Bill', 'Pat', 'Sue', 'Ted', 'Ray', 'Art']:
            assert case_mode(name) == NOT_LOWERCASE, name

    def test_only_plain_lowercase_words(self):
        assert len(COMMON_WORDS) > 10000
        assert all(w.isalpha() and w.islower() and len(w) >= 3 for w in COMMON_WORDS)

    def test_which_common_australian_names_are_caught(self):
        """
        A fixed sample of common Australian given names and surnames. Being on
        the list means "matched only when not all lowercase" — harmless for a
        name, which prose never writes in lowercase. This test pins the set so
        a change to the list that catches a new name fails HERE, where someone
        reads it, rather than surprising a teacher.
        """
        sample = """Smith Jones Williams Brown Wilson Taylor Johnson White Martin
        Anderson Thompson Nguyen Thomas Walker Harris Lee Ryan Robinson Kelly King
        Davis Wright Evans Roberts Green Hall Wood Jackson Clarke Patel Khan Lewis
        James Phillips Mitchell Turner Young Cook Hill Scott Long Singh Chen Wang
        Tran Pham Kim Park Baker Campbell Stewart Murphy Edwards Morris Moore Clark
        Bell Parker Cooper Hughes Price Ward Hunter Carter Mason Fisher Graham Page
        Stone Knight Oliver Noah Jack William Leo Lucas Henry Charlie Charlotte
        Amelia Isla Olivia Mia Ava Grace Willow Harper Chloe Ruby Sophie Ella Zoe
        Lily Ivy Archie Max Hope Will Summer Autumn Jade Rose Violet Daisy Poppy
        Hazel Pearl Joy Faith Mark Grant Bill Pat Sue Ray Art Ted Bob Rob Penny
        May June Frank Victoria Christian Patience Harmony""".split()
        caught = sorted(n for n in sample if case_mode(n) == NOT_LOWERCASE)
        assert caught == sorted("""Art Autumn Baker Bell Bill Bob Brown Christian
        Cook Daisy Faith Frank Grace Grant Green Hall Harmony Hazel Hill Hope
        Hunter Ivy Jack Jade Joy June King Knight Lee Long Mark Mason Max May
        Pat Page Park Patience Pearl Penny Poppy Price Ray Rob Rose Ruby Smith
        Stone Sue Summer Ted Violet Walker Ward White Will Wood Young""".split())


class TestDetection:

    def test_lowercase_word_is_not_offered(self):
        orch = PIIOrchestrator("William Young", parent_names=["Grace Long"])
        found = _texts(orch.detect_pii_in_text(
            "Young people will need long breaks and a grace period.", 1))
        assert 'young' not in found
        assert 'long' not in found and 'grace' not in found

    def test_capitalised_and_capitals_are_offered(self):
        orch = PIIOrchestrator("William Young", parent_names=["Grace Long"])
        found = _texts(orch.detect_pii_in_text("Mr Young spoke to Mrs Long.", 1))
        assert 'Young' in found and 'Long' in found
        found = _texts(orch.detect_pii_in_text("STUDENT: YOUNG", 1))
        assert 'YOUNG' in found

    def test_name_row_survives_a_lowercase_word_on_the_same_line(self):
        """Deduplication keys on lowercase text; the lowercase hit must be
        dropped before it can displace the name."""
        orch = PIIOrchestrator("William Young")
        matches = orch.detect_pii_in_text("Mr Young said young people thrive.", 1)
        assert [m.text for m in matches if m.text.lower() == 'young'] == ['Young']

    def test_sentence_initial_word_is_still_offered(self):
        """The accepted trade-off, as rule 7 accepted it for "Do" and "He"."""
        orch = PIIOrchestrator("William Young")
        found = _texts(orch.detect_pii_in_text("Young people often need breaks.", 1))
        assert 'Young' in found

    def test_full_name_is_unaffected(self):
        orch = PIIOrchestrator("William Young")
        found = _texts(orch.detect_pii_in_text("william young was absent", 1))
        assert 'william young' in found

    def test_uncommon_name_still_matches_in_lowercase(self):
        orch = PIIOrchestrator("Minh Nguyen")
        found = _texts(orch.detect_pii_in_text("contact nguyen family", 1))
        assert 'nguyen' in found
