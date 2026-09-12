import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.arrangement import ArrangementScore
from ufor.codec import parse_score, score_toml
from ufor.streams import AudioType


def test_documented_arrangement_separates_ports_from_destinations() -> None:
    path = Path(__file__).parents[1] / 'doc/arrangement-format.md'
    text = re.search(r'```toml\n(.*?)```', path.read_text(), re.DOTALL)
    assert text is not None
    document = parse_score(text[1])
    assert document.outputs[0].name == document.destinations[0].output
    assert 'path' not in document.outputs[0].model_dump()
    assert parse_score(score_toml(document)) == document
    assert ArrangementScore.model_json_schema()['properties']['body']


def test_audio_ports_reject_other_quantities_and_duplicate_channels() -> None:
    with pytest.raises(ValidationError):
        AudioType.model_validate(
            {'timebase': 'audio', 'channels': ['left'], 'quantity': 'voltage'}
        )
    with pytest.raises(ValidationError, match='duplicate'):
        AudioType(timebase='audio', channels=['left', 'left'])


def arrangement_data() -> dict[str, object]:
    return {
        'name': 'test',
        'title': 'Test',
        'timebases': [{'name': 'audio', 'rate': {'numerator': 48000}}],
        'outputs': [
            {
                'name': 'out',
                'stream': {'timebase': 'audio', 'channels': ['mono']},
                'binding': {'bus': 'bus'},
            }
        ],
        'body': {
            'timebase': 'audio',
            'parts': [{'name': 'source', 'score': {'path': 'audio.toml'}}],
            'tracks': [
                {'name': 'track', 'stream': {'timebase': 'audio', 'channels': ['mono']}}
            ],
            'buses': [
                {'name': 'bus', 'stream': {'timebase': 'audio', 'channels': ['mono']}}
            ],
            'clips': [
                {
                    'name': 'clip',
                    'source': {'name': 'source', 'output': 'audio'},
                    'track': 'track',
                    'source_start': 0,
                    'source_end': 48000,
                    'timeline_start': 0,
                }
            ],
            'routes': [{'source': 'track', 'destination': 'bus'}],
        },
    }


@pytest.mark.parametrize(
    'area, field, value',
    [
        ('clips', 'source', {'name': 'missing', 'output': 'audio'}),
        ('clips', 'track', 'missing'),
        ('routes', 'source', 'missing'),
        ('routes', 'destination', 'missing'),
        ('routes', 'source', 'bus'),
        ('buses', 'name', 'track'),
        ('clips', 'source_start', False),
        ('clips', 'timeline_start', 1.0),
        ('routes', 'gain', float('nan')),
    ],
)
def test_arrangement_rejects_invalid_graphs_and_numeric_values(
    area: str, field: str, value: object
) -> None:
    data = arrangement_data()
    data['body'][area][0][field] = value
    with pytest.raises(ValidationError):
        ArrangementScore.model_validate(data)


@pytest.mark.parametrize('area', ['parts', 'tracks', 'buses', 'clips', 'routes'])
def test_arrangement_rejects_duplicate_identities(area: str) -> None:
    data = arrangement_data()
    data['body'][area].append(data['body'][area][0])
    with pytest.raises(ValidationError, match='duplicate'):
        ArrangementScore.model_validate(data)


def test_arrangement_requires_matching_layouts_and_existing_output_ports() -> None:
    data = arrangement_data()
    data['body']['buses'][0]['stream']['channels'] = ['other']
    with pytest.raises(ValidationError, match='layouts'):
        ArrangementScore.model_validate(data)
    data = arrangement_data()
    data['destinations'] = [{'output': 'missing', 'path': 'out.wav', 'format': 'wav'}]
    with pytest.raises(ValidationError, match='output'):
        ArrangementScore.model_validate(data)


def test_arrangement_orders_dependent_buses_and_checks_control_clips() -> None:
    data = arrangement_data()
    data['body']['buses'].insert(
        0, {'name': 'master', 'stream': {'timebase': 'audio', 'channels': ['mono']}}
    )
    data['body']['routes'].append({'source': 'bus', 'destination': 'master'})
    assert ArrangementScore.model_validate(data).body.bus_order == ['bus', 'master']
    data['body']['control_clips'] = [
        {
            'name': 'fade',
            'source': {'name': 'missing', 'output': 'control'},
            'source_start': 0,
            'source_end': 1,
            'timeline_start': 0,
        }
    ]
    with pytest.raises(ValidationError, match='unknown source'):
        ArrangementScore.model_validate(data)
