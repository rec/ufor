import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import ufor.synth_trace
from ufor.codec import parse_score, score_schema, score_toml
from ufor.events import ControlChange, Release, Trigger
from ufor.instrument_trace import LifecycleSnapshot, RetirementCause, VoiceRetirement
from ufor.synth import SynthInstrumentScore


def fixture() -> dict[str, object]:
    return json.loads(
        (Path(__file__).parents[1] / 'conformance/synth-instrument.json').read_text()
    )


def test_synth_instrument_conformance_round_trips_through_the_common_codec() -> None:
    document = SynthInstrumentScore.model_validate(fixture())
    assert parse_score(score_toml(document)) == document
    assert (
        SynthInstrumentScore.model_validate_json(document.model_dump_json()) == document
    )
    assert 'synth_instrument' in score_schema()['discriminator']['mapping']


def test_synth_instrument_validates_controls_and_voice_routes() -> None:
    document = SynthInstrumentScore.model_validate(fixture())
    document.body.validate_event(
        Trigger(
            tick=0,
            ordinal=0,
            part='main',
            trigger_id='note-a',
            key=69,
            controls={'sustain': 1},
        )
    )
    document.body.validate_event(
        ControlChange(
            tick=1,
            ordinal=0,
            control='sustain',
            value=0,
            scope='part',
            part='main',
        )
    )
    invalid_control = fixture()
    invalid_control['body']['controls'] = {'sustain': {'polarity': 'bipolar'}}
    with pytest.raises(ValidationError, match='Sustain requires a unipolar control'):
        SynthInstrumentScore.model_validate(invalid_control)
    invalid_route = fixture()
    invalid_route['body']['voices'][0]['channels'][0]['input'] = 'left'
    with pytest.raises(ValidationError, match='require mono input'):
        SynthInstrumentScore.model_validate(invalid_route)


def test_synth_instrument_rejects_sample_traversal_fields() -> None:
    raw = fixture()
    raw['body']['voices'][0]['slice'] = 'not-a-synth-voice'
    with pytest.raises(ValidationError):
        SynthInstrumentScore.model_validate(raw)


def test_synth_trace_uses_the_shared_lifecycle_contract() -> None:
    raw = fixture()
    for name, trigger in [
        ('release', 'release'),
        ('logical-release', 'logical_release'),
    ]:
        voice = raw['body']['voices'][0].copy()
        voice.update({'name': name, 'trigger': trigger})
        raw['body']['voices'].append(voice)
    result = ufor.synth_trace.prepare(
        SynthInstrumentScore.model_validate(raw).body,
        [
            Trigger(tick=0, ordinal=0, part='main', trigger_id='note-a', key=69),
            Release(tick=1, ordinal=0, part='main', trigger_id='note-a'),
            Release(tick=2, ordinal=0, part='main', trigger_id='note-a'),
        ],
        seed=42,
    )
    starts = [a for a in result.actions if isinstance(a, ufor.synth_trace.VoiceStart)]
    assert [a.template for a in starts] == ['triangle', 'release', 'logical-release']
    assert [a.cause for a in result.actions if isinstance(a, VoiceRetirement)] == [
        RetirementCause.logical_release
    ]
    assert isinstance(result.snapshots[0], LifecycleSnapshot)
    assert result.snapshots[0].triggers[0].templates == ['triangle']
    assert result.actions[-1].kind == 'voice_retirement'
