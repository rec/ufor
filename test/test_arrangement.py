import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.arrangement import ArrangementDocument
from ufor.codec import document_toml, parse_document
from ufor.streams import AudioType


def test_documented_arrangement_separates_ports_from_destinations() -> None:
    path = Path(__file__).parents[1] / 'doc/arrangement-format.md'
    text = re.search(r'```toml\n(.*?)```', path.read_text(), re.DOTALL)
    assert text is not None
    document = parse_document(text[1])
    assert document.ports[0].id == document.destinations[0].port
    assert 'path' not in document.ports[0].model_dump()
    assert parse_document(document_toml(document)) == document
    assert ArrangementDocument.model_json_schema()['properties']['body']


def test_audio_ports_reject_other_quantities_and_duplicate_channels() -> None:
    with pytest.raises(ValidationError):
        AudioType.model_validate(
            {'timebase': 'audio', 'channels': ['left'], 'quantity': 'voltage'}
        )
    with pytest.raises(ValidationError, match='duplicate'):
        AudioType(timebase='audio', channels=['left', 'left'])


def arrangement_data() -> dict[str, object]:
    return {
        'id': 'test',
        'name': 'Test',
        'timebases': [{'id': 'audio', 'rate': {'numerator': 48000}}],
        'ports': [
            {
                'id': 'out',
                'direction': 'output',
                'stream': {'timebase': 'audio', 'channels': ['mono']},
                'binding': {'bus': 'bus'},
            }
        ],
        'body': {
            'timebase': 'audio',
            'nodes': [{'id': 'source', 'definition': {'path': 'audio.toml'}}],
            'tracks': [
                {'id': 'track', 'stream': {'timebase': 'audio', 'channels': ['mono']}}
            ],
            'buses': [
                {'id': 'bus', 'stream': {'timebase': 'audio', 'channels': ['mono']}}
            ],
            'clips': [
                {
                    'id': 'clip',
                    'source': {'node': 'source', 'port': 'audio'},
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
        ('clips', 'source', {'node': 'missing', 'port': 'audio'}),
        ('clips', 'track', 'missing'),
        ('routes', 'source', 'missing'),
        ('routes', 'destination', 'missing'),
        ('routes', 'source', 'bus'),
        ('buses', 'id', 'track'),
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
        ArrangementDocument.model_validate(data)


@pytest.mark.parametrize('area', ['nodes', 'tracks', 'buses', 'clips', 'routes'])
def test_arrangement_rejects_duplicate_identities(area: str) -> None:
    data = arrangement_data()
    data['body'][area].append(data['body'][area][0])
    with pytest.raises(ValidationError, match='duplicate'):
        ArrangementDocument.model_validate(data)


def test_arrangement_requires_matching_layouts_and_existing_output_ports() -> None:
    data = arrangement_data()
    data['body']['buses'][0]['stream']['channels'] = ['other']
    with pytest.raises(ValidationError, match='layouts'):
        ArrangementDocument.model_validate(data)
    data = arrangement_data()
    data['destinations'] = [{'port': 'missing', 'path': 'out.wav', 'format': 'wav'}]
    with pytest.raises(ValidationError, match='output port'):
        ArrangementDocument.model_validate(data)


def test_arrangement_orders_dependent_buses_and_checks_automation() -> None:
    data = arrangement_data()
    data['body']['buses'].insert(
        0, {'id': 'master', 'stream': {'timebase': 'audio', 'channels': ['mono']}}
    )
    data['body']['routes'].append({'source': 'bus', 'destination': 'master'})
    assert ArrangementDocument.model_validate(data).body.bus_order == ['bus', 'master']
    data['body']['automation'] = [
        {
            'target': {'kind': 'clip', 'node': 'missing'},
            'points': [{'frame': 0, 'value': 1}],
        }
    ]
    with pytest.raises(ValidationError, match='Unknown automation'):
        ArrangementDocument.model_validate(data)
