import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.codec import parse_score, score_toml
from ufor.events import Trigger
from ufor.synth import SynthInstrumentScore
from ufor.synth_trace import VoiceStart, prepare


def document() -> dict:
    return json.loads(
        (Path(__file__).parents[1] / 'conformance/tx81z-output.json').read_text()
    )


def test_shared_tx81z_output_round_trips_and_preserves_voice_identity() -> None:
    raw = document()
    raw['body']['voices'].append({**raw['body']['voices'][0], 'name': 'second'})
    raw['body']['tx81z_outputs'][0]['voices'].append('second')
    raw['body']['voices'][0]['processing'] = {'tuning_cents': 12}
    raw['body']['tx81z_outputs'][0]['processing']['filters'] = [
        {'name': 'lowpass', 'response': 'lowpass', 'cutoff_hz': 2000}
    ]
    score = SynthInstrumentScore.model_validate(raw)
    assert parse_score(score_toml(score)) == score
    assert SynthInstrumentScore.model_validate_json(score.model_dump_json()) == score
    result = prepare(
        score.body,
        [Trigger(tick=0, ordinal=0, part='main', trigger_id='note', key=69)],
        seed=0,
    )
    starts = [a for a in result.actions if isinstance(a, VoiceStart)]
    assert {a.template for a in starts} == {'patch', 'second'}
    assert all(not a.settings.channels for a in starts)


@pytest.mark.parametrize(
    'case', ['missing', 'duplicate', 'two_outputs', 'unowned', 'routed', 'dx7']
)
def test_tx81z_outputs_require_unambiguous_template_ownership(case: str) -> None:
    raw = document()
    body = raw['body']
    output = body['tx81z_outputs'][0]
    voice = body['voices'][0]
    if case == 'missing':
        output['voices'] = ['unknown']
    elif case == 'duplicate':
        output['voices'] *= 2
    elif case == 'two_outputs':
        body['tx81z_outputs'].append({**deepcopy(output), 'name': 'other'})
    elif case == 'unowned':
        body['tx81z_outputs'] = []
    elif case == 'routed':
        voice['channels'] = output['channels']
    else:
        voice.update(yamaha='dx7', patch=bytes(155).hex(), channels=output['channels'])
        del voice['additional']
    with pytest.raises(ValidationError):
        SynthInstrumentScore.model_validate(raw)


@pytest.mark.parametrize(
    'owner,field,value',
    [
        ('voice', 'volume_db', -6),
        ('voice', 'invert_polarity', True),
        ('output', 'tuning_cents', 1),
        ('output', 'pan', 0.5),
    ],
)
def test_tx81z_processing_cannot_cross_the_shared_dac_boundary(
    owner: str, field: str, value: object
) -> None:
    raw = document()
    item = raw['body']['voices' if owner == 'voice' else 'tx81z_outputs'][0]
    item['processing'] = {field: value}
    with pytest.raises(ValidationError):
        SynthInstrumentScore.model_validate(raw)


def test_grouped_tx81z_rejects_per_voice_host_gain_modulation() -> None:
    raw = document()
    raw['body']['voices'][0]['modulation'] = {
        'parameters': [
            {
                'target': {'name': 'processing', 'parameter': 'amplitude'},
                'unit': 'ratio',
                'scope': 'voice',
                'minimum': 0,
                'maximum': 1,
                'default': 1,
            }
        ]
    }
    with pytest.raises(ValidationError, match='Grouped TX81Z voices allow tuning'):
        SynthInstrumentScore.model_validate(raw)


@pytest.mark.parametrize('field,value', [('input', 'left'), ('output', 'unknown')])
def test_tx81z_output_routes_require_mono_and_known_destinations(
    field: str, value: str
) -> None:
    raw = document()
    raw['body']['tx81z_outputs'][0]['channels'][0][field] = value
    with pytest.raises(ValidationError, match='mono input and known outputs'):
        SynthInstrumentScore.model_validate(raw)
