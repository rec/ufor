import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from ufor.events import PerformanceEvent, Release, Trigger
from ufor.instrument_trace import VoiceRetirement
from ufor.samples import trace
from ufor.samples.instrument import SampleInstrument


@pytest.mark.parametrize('name', ['note-conditions', 'control-triggers'])
def test_selection_matches_portable_event_vectors(name: str) -> None:
    case = json.loads(Path(f'conformance/{name}.json').read_text())
    instrument = SampleInstrument.model_validate(case['instrument'])
    events = TypeAdapter(list[PerformanceEvent]).validate_python(case['events'])
    result = trace.prepare(instrument, events, seed=1)
    starts = [a for a in result.actions if isinstance(a, trace.VoiceStart)]
    assert [[a.tick, a.template] for a in starts] == case['starts']
    assert result.snapshots[0].selection.previous_keys == case['previous_keys']
    assert result.snapshots[0].selection.held_keys == case['held_keys']
    assert trace.SampleTrace.model_validate_json(result.model_dump_json()) == result
    if name == 'control-triggers':
        assert [
            [a.tick, a.cause.value]
            for a in result.actions
            if isinstance(a, VoiceRetirement)
        ] == case['retirements']
        assert all(a.key is None and a.trigger_id is None for a in starts)
        assert starts[0].pitch_hz == 220
        assert starts[0].velocity == 0.75
        assert result.snapshots[0].selection.note_on_counts == {}
        assert len(result.snapshots[0].voices) == 3


def test_held_key_is_updated_before_same_event_selection() -> None:
    case = json.loads(Path('conformance/note-conditions.json').read_text())
    raw = case['instrument']
    raw['settings']['articulations'] = None
    raw['slots'][0]['mapping']['lowest_key'] = 24
    raw['slots'][0]['key_conditions'] = [{'key': 24, 'pressed': True}]
    result = trace.prepare(
        SampleInstrument.model_validate(raw),
        [Trigger(tick=0, ordinal=0, part='main', trigger_id='self', key=24)],
        seed=1,
    )
    assert sum(isinstance(a, trace.VoiceStart) for a in result.actions) == 1


def test_control_trigger_chokes_existing_voices_without_a_note_identity() -> None:
    case = json.loads(Path('conformance/control-triggers.json').read_text())
    raw = case['instrument']
    raw['slots'][0]['choke_group'] = 'pedal'
    raw['slots'][0]['chokes'] = [{'group': 'pedal', 'mode': 'immediate'}]
    result = trace.prepare(
        SampleInstrument.model_validate(raw),
        TypeAdapter(list[PerformanceEvent]).validate_python(case['events'][:4]),
        seed=1,
    )
    retirements = [a for a in result.actions if isinstance(a, VoiceRetirement)]
    assert len(retirements) == 1
    assert retirements[0].cause == 'choke'
    assert retirements[0].tick == 3


def test_release_selection_observes_physical_key_release_before_sustain() -> None:
    case = json.loads(Path('conformance/note-conditions.json').read_text())
    raw = case['instrument']
    raw['settings']['articulations'] = None
    note, tail = raw['slots']
    note['key_conditions'] = []
    tail.pop('previous_key')
    tail.update(
        trigger='release',
        playback={'mode': 'one_shot'},
        key_conditions=[{'key': 60, 'pressed': False}],
    )
    result = trace.prepare(
        SampleInstrument.model_validate(raw),
        [
            Trigger(tick=0, ordinal=0, part='main', trigger_id='note', key=60),
            Release(tick=1, ordinal=1, part='main', trigger_id='note'),
        ],
        seed=1,
    )
    starts = [a for a in result.actions if isinstance(a, trace.VoiceStart)]
    assert len(starts) == 2
    assert starts[1].tick == 1
    assert starts[1].template == 'previous'


@pytest.mark.parametrize(
    'change',
    [{'control': 'missing'}, {'maximum_value': 2}, {'velocity': 2}, {'pitch_hz': 0}],
)
def test_control_trigger_requires_declared_control_and_valid_voice_properties(
    change: dict[str, object],
) -> None:
    case = json.loads(Path('conformance/control-triggers.json').read_text())
    raw = case['instrument']
    raw['slots'][0]['control_trigger'].update(change)
    with pytest.raises(ValidationError):
        SampleInstrument.model_validate(raw)


def test_previous_key_survives_release_and_unmatched_note_ons() -> None:
    case = json.loads(Path('conformance/note-conditions.json').read_text())
    raw = case['instrument']
    raw['slots'] = [raw['slots'][1]]
    raw['slots'][0]['previous_key'] = 10
    result = trace.prepare(
        SampleInstrument.model_validate(raw),
        [
            Trigger(tick=0, ordinal=0, part='main', trigger_id='unmatched', key=10),
            Release(tick=1, ordinal=1, part='main', trigger_id='unmatched'),
            Trigger(tick=100, ordinal=2, part='main', trigger_id='matched', key=60),
        ],
        seed=1,
    )
    starts = [a for a in result.actions if isinstance(a, trace.VoiceStart)]
    assert len(starts) == 1
    assert starts[0].tick == 100
