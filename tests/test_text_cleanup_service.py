import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

from pii_detector import PIIMatch
from pseudonym_map import PseudonymMap
from src.services.text_cleanup_service import BLOCK, blackout, deidentify_paste


def match(text, category='Student name'):
    return PIIMatch(text=text, category=category, confidence=0.95,
                    page_num=1, line_num=1, context=text, source='regex')


def test_blackout_replaces_pii_with_a_fixed_width_block():
    cleaned, count, leftovers = blackout(
        'Billy Bob was absent.', [match('Billy Bob')])
    assert cleaned == f'{BLOCK} was absent.'
    assert count == 1
    assert leftovers == []


def test_block_width_does_not_reveal_the_length_of_what_was_removed():
    short, _, _ = blackout('Jo went home.', [match('Jo')])
    long, _, _ = blackout('Bartholomew went home.', [match('Bartholomew')])
    assert short.split(' ')[0] == long.split(' ')[0]


def test_longest_first_ordering_is_inherited():
    cleaned, count, _ = blackout(
        'Billy Bob and Billy.', [match('Billy Bob'), match('Billy')])
    assert cleaned == f'{BLOCK} and {BLOCK}.'
    assert count == 2


def test_form_label_words_are_still_blacked_out():
    # Diverges from PseudonymMap.should_replace (CLAUDE.md rule 58) on purpose:
    # over-removal is the correct bias for the redact pathway (rule 54a).
    cleaned, count, _ = blackout(
        'Phone: 0412 345 678', [match('Phone', 'Family/parent (contextual)')])
    assert cleaned.startswith(BLOCK)
    assert count == 1


def test_nothing_selected_returns_the_text_unchanged():
    cleaned, count, leftovers = blackout('Nothing here.', [])
    assert (cleaned, count, leftovers) == ('Nothing here.', 0, [])


def test_deidentify_replaces_the_student_with_a_role_label():
    pmap = PseudonymMap(student_name='Billy Bob')
    cleaned, count, leftovers = deidentify_paste(
        'Billy Bob was absent.', [match('Billy Bob')], pmap)
    assert cleaned == '[Student] was absent.'
    assert count == 1
    assert leftovers == []


def test_verification_uses_the_same_gate_as_replacement():
    # "Phone" is a form label; should_replace() declines it. Verifying it anyway
    # would report a leftover on correct output (CLAUDE.md rule 58).
    pmap = PseudonymMap(student_name='Billy Bob')
    cleaned, _, leftovers = deidentify_paste(
        'Phone: 0412 345 678', [match('Phone', 'Family/parent (contextual)')], pmap)
    assert cleaned == 'Phone: 0412 345 678'
    assert leftovers == []


def test_every_occurrence_of_a_repeated_name_is_replaced():
    # Both occurrences of the selected text are consumed by the single-pass
    # replace, so nothing is left to report as a leftover.
    pmap = PseudonymMap(student_name='Billy Bob')
    cleaned, _, leftovers = deidentify_paste(
        'Billy Bob and Billy Bob', [match('Billy Bob')], pmap)
    assert leftovers == []
    assert 'Billy' not in cleaned
