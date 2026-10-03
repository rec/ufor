from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.arpeggiator_capture import CapturedPhrase, Occurrence
from ufor.control import Clock


@pytest.mark.parametrize('name', ['held-chord', 'wind-breath', 'gap', 'marked-sample'])
def test_capture_fixtures_preserve_source_identity_and_ledger(name: str) -> None:
    text = Path(f'conformance/arpeggiator/{name}.json').read_text()
    phrase = CapturedPhrase.model_validate_json(text)
    assert CapturedPhrase.model_validate_json(phrase.model_dump_json()) == phrase
    assert len({n.note_id for n in phrase.notes}) == len(phrase.notes)


def test_wind_notes_keep_expression_and_inherited_entry_state() -> None:
    phrase = CapturedPhrase.model_validate_json(
        Path('conformance/arpeggiator/wind-breath.json').read_text()
    )
    c, e = phrase.notes
    assert c.expression_events == [2, 3, 4]
    assert c.following_events == [6]
    assert e.entry_state['breath'].source_event == 6
    assert e.entry_state['bend'].source_event == 4
    assert e.expression_events == [8]


def test_gap_observation_is_retained_without_becoming_note_expression() -> None:
    phrase = CapturedPhrase.model_validate_json(
        Path('conformance/arpeggiator/gap.json').read_text()
    )
    c, e = phrase.notes
    assert phrase.prefix_events == [0]
    assert c.following_events == [3]
    assert 3 not in c.expression_events
    assert e.entry_state['breath'].source_event == 3
    assert e.following_events == [6]


def test_marked_regions_partition_the_source_frames() -> None:
    phrase = CapturedPhrase.model_validate_json(
        Path('conformance/arpeggiator/marked-sample.json').read_text()
    )
    assert [n.selection_key for n in phrase.notes] == [60, 62, 64]
    assert [
        (n.region.start_frame, n.region.end_frame) for n in phrase.notes if n.region
    ] == [
        (0, 16000),
        (16000, 32000),
        (32000, 48000),
    ]


def test_occurrences_have_distinct_output_identities_for_one_source() -> None:
    common = {
        'source_capture': 'held',
        'source_note': 'c',
        'bank_revision': 0,
        'destination': 'midi',
        'clock': Clock.beats,
    }
    first = Occurrence(
        **common, decision=0, trigger_id='first', onset=0, gate_end=Fraction(1, 5)
    )
    second = Occurrence(
        **common,
        decision=1,
        trigger_id='second',
        onset=Fraction(1, 4),
        gate_end=Fraction(9, 20),
    )
    assert first.source_note == second.source_note
    assert first.trigger_id != second.trigger_id
    assert first.gate_end < second.onset


def test_phrase_rejects_event_references_outside_its_ledger() -> None:
    phrase = CapturedPhrase.model_validate_json(
        Path('conformance/arpeggiator/gap.json').read_text()
    )
    note = phrase.notes[0].model_copy(
        update={'expression_events': [len(phrase.events)]}
    )
    with pytest.raises(ValidationError, match='outside the phrase ledger'):
        CapturedPhrase.model_validate(
            phrase.model_dump() | {'notes': [note, phrase.notes[1]]}
        )
