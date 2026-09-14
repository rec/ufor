import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.codec import parse_score, score_schema, score_toml
from ufor.events import ControlChange, Trigger
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
