import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.codec import parse_score, score_schema, score_toml
from ufor.performance_binding import PerformanceBindingScore


def test_performance_binding_round_trips_with_explicit_midi_pairing() -> None:
    raw = json.loads(Path('conformance/performance-binding.json').read_text())
    score = PerformanceBindingScore.model_validate(raw)

    assert parse_score(score_toml(score)) == score
    assert PerformanceBindingScore.model_validate_json(score.model_dump_json()) == score
    assert 'performance_binding' in score_schema()['discriminator']['mapping']
    assert score.body.midi[0].controllers[0].control == 'sustain'


@pytest.mark.parametrize(
    ('change', 'message'),
    [
        ({'channels': [0]}, 'greater than or equal to 1'),
        ({'channels': [1, 1]}, 'duplicate MIDI channel'),
        ({'repeated_key_release': None}, 'repeated_key_release'),
        ({'controllers': [{'number': 128, 'control': 'sustain'}]}, 'less than'),
        (
            {
                'controllers': [
                    {'number': 64, 'control': 'sustain'},
                    {'number': 64, 'control': 'expression'},
                ]
            },
            'duplicate MIDI controller',
        ),
        (
            {'controllers': [{'number': 64, 'control': 'sustain', 'minimum': 1.0}]},
            'output range must increase',
        ),
    ],
)
def test_performance_binding_rejects_ambiguous_midi_sources(
    change: dict[str, object], message: str
) -> None:
    raw = json.loads(Path('conformance/performance-binding.json').read_text())
    raw['body']['midi'][0].update(change)
    with pytest.raises(ValidationError, match=message):
        PerformanceBindingScore.model_validate(raw)


def test_performance_binding_channels_must_not_overlap_between_parts() -> None:
    raw = json.loads(Path('conformance/performance-binding.json').read_text())
    second = deepcopy(raw['body']['midi'][0])
    second['part'] = 'other'
    raw['body']['midi'].append(second)
    with pytest.raises(ValidationError, match='duplicate MIDI channel'):
        PerformanceBindingScore.model_validate(raw)
