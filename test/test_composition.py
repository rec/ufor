import json
from pathlib import Path

import pytest

from ufor.arrangement import ArrangementDocument
from ufor.codec import document_toml, parse_document
from ufor.composition import Composition, DefinitionRecord
from ufor.samples.instrument import InstrumentDocument
from ufor.sequence import SequenceDocument


def definitions() -> dict[str, DefinitionRecord]:
    piano = json.loads(Path('conformance/instrument.json').read_text())
    output = next(p for p in piano['ports'] if p['direction'] == 'output')['stream']
    piano['body']['instrument']['modulation']['parameters'] = [
        {
            'target': {'node': 'processing', 'parameter': 'volume_db'},
            'unit': 'db',
            'scope': 'voice',
            'minimum': -60,
            'maximum': 6,
            'default': 0,
        }
    ]
    piano['parameters'] = [
        {'id': 'level', 'binding': {'node': 'processing', 'parameter': 'volume_db'}}
    ]
    notes = SequenceDocument.model_validate(
        {
            'id': 'notes',
            'name': 'Notes',
            'timebases': [{'id': 'ticks', 'rate': {'numerator': 1000}}],
            'ports': [
                {
                    'id': 'notes',
                    'direction': 'output',
                    'stream': {
                        'family': 'event',
                        'timebase': 'ticks',
                        'kinds': ['trigger', 'release'],
                    },
                    'binding': {'sequence': True},
                }
            ],
            'body': {
                'timebase': 'ticks',
                'start': 0,
                'end': 2000,
                'events': [
                    {
                        'kind': 'trigger',
                        'tick': 10,
                        'ordinal': 0,
                        'part': 'part',
                        'trigger_id': 'note',
                        'key': 69,
                        'pitch_hz': 261.625565,
                        'velocity': 0.5,
                    },
                    {
                        'kind': 'release',
                        'tick': 900,
                        'ordinal': 1,
                        'part': 'part',
                        'trigger_id': 'note',
                    },
                ],
            },
        }
    )
    mix = ArrangementDocument.model_validate(
        {
            'id': 'mix',
            'name': 'Mix',
            'timebases': [{'id': 'output', 'rate': {'numerator': 48000}}],
            'ports': [
                {
                    'id': 'main',
                    'direction': 'output',
                    'stream': output,
                    'binding': {'track': 'mix', 'end': 96000},
                }
            ],
            'body': {
                'timebase': 'output',
                'nodes': [
                    {'id': 'notes', 'definition': {'path': 'notes.toml'}},
                    {
                        'id': 'piano',
                        'definition': {'path': 'piano.toml'},
                        'parameters': {'level': -6},
                    },
                ],
                'connections': [
                    {
                        'source': {'node': 'notes', 'port': 'notes'},
                        'destination': {'node': 'piano', 'port': 'performance'},
                    }
                ],
                'tracks': [{'id': 'mix', 'stream': output}],
                'clips': [
                    {
                        'id': 'piano',
                        'source': {'node': 'piano', 'port': 'audio'},
                        'track': 'mix',
                        'source_start': 0,
                        'source_end': 96000,
                        'timeline_start': 0,
                    }
                ],
            },
        }
    )
    return {
        'mix': DefinitionRecord(
            document=mix, references={'notes.toml': 'notes', 'piano.toml': 'piano'}
        ),
        'notes': DefinitionRecord(document=notes),
        'piano': DefinitionRecord(document=InstrumentDocument.model_validate(piano)),
    }


def test_sequence_drives_an_independently_configured_instrument() -> None:
    values = definitions()
    composition = Composition('mix', values)
    assert composition.instances['root/piano'].parameters == {'level': -6}
    trace = composition.performance_trace(96000)
    assert [(e.instance, e.event.kind, e.event.tick) for e in trace] == [
        ('root/piano', 'trigger', 480),
        ('root/piano', 'release', 43200),
    ]
    assert composition.performance_trace(96000, start=48000) == trace
    assert (
        parse_document(document_toml(values['mix'].document)) == values['mix'].document
    )


def test_cropped_nested_instances_replay_their_own_histories() -> None:
    values = definitions()
    mix = values['mix'].document
    raw = mix.model_dump()
    raw['body']['nodes'] = [
        {'id': n, 'definition': {'path': 'mix.toml'}} for n in ('first', 'second')
    ]
    raw['body']['connections'] = []
    raw['body']['clips'] = [
        {
            'id': n,
            'source': {'node': n, 'port': 'main'},
            'track': 'mix',
            'source_start': 48000,
            'source_end': 96000,
            'timeline_start': 0,
        }
        for n in ('first', 'second')
    ]
    raw['ports'][0]['binding']['end'] = 48000
    values['outer'] = DefinitionRecord(
        document=ArrangementDocument.model_validate(raw), references={'mix.toml': 'mix'}
    )
    composition = Composition('outer', values)
    assert composition.evaluation_windows(0, 48000)[('root/first/piano', 'audio')] == (
        48000,
        96000,
    )
    trace = composition.performance_trace(48000)
    assert len(trace) == 4
    assert {e.instance for e in trace} == {'root/first/piano', 'root/second/piano'}
    assert composition.performance_trace(48000) == trace


@pytest.mark.parametrize(
    'change, message',
    [
        ('missing', 'Missing|missing'),
        ('private', 'unknown public port'),
        ('parameter', 'unknown public parameters'),
        ('range', 'outside public range'),
        ('cycle', 'cycle'),
        ('pin', 'digest'),
    ],
)
def test_resolution_rejects_invalid_references_and_configuration(
    change: str, message: str
) -> None:
    values = definitions()
    raw = values['mix'].document.model_dump()
    if change == 'missing':
        del values['piano']
    elif change == 'private':
        raw['body']['clips'][0]['source']['port'] = 'private'
    elif change == 'parameter':
        raw['body']['nodes'][1]['parameters'] = {'private': 0}
    elif change == 'range':
        raw['body']['nodes'][1]['parameters'] = {'level': 20}
    elif change == 'cycle':
        values['mix'] = values['mix'].model_copy(
            update={'references': {'notes.toml': 'mix', 'piano.toml': 'piano'}}
        )
    elif change == 'pin':
        raw['body']['nodes'][1]['definition']['sha256'] = 'f' * 64
    if change != 'cycle':
        values['mix'] = values['mix'].model_copy(
            update={'document': ArrangementDocument.model_validate(raw)}
        )
    with pytest.raises(ValueError, match=message):
        Composition('mix', values)


def test_unrepresentable_event_ticks_and_missing_pitch_are_rejected() -> None:
    for bad_clock in (True, False):
        values = definitions()
        raw = values['notes'].document.model_dump()
        if bad_clock:
            raw['timebases'][0]['rate']['numerator'] = 1001
        else:
            raw['body']['events'][0]['pitch_hz'] = None
        values['notes'] = DefinitionRecord(
            document=SequenceDocument.model_validate(raw)
        )
        with pytest.raises(ValueError, match='integer tick|pitch_hz'):
            Composition('mix', values)


def test_parent_parameter_inherits_child_configuration_and_can_narrow_it() -> None:
    values = definitions()
    raw = values['mix'].document.model_dump()
    raw['parameters'] = [
        {
            'id': 'volume',
            'binding': {'node': 'piano', 'parameter': 'level'},
            'minimum': -30,
            'maximum': 0,
        }
    ]
    values['mix'] = values['mix'].model_copy(
        update={'document': ArrangementDocument.model_validate(raw)}
    )
    composition = Composition('mix', values, {'volume': -12})
    assert composition.parameter_contract('mix', 'volume').default == -6
    assert composition.instances['root/piano'].parameters['level'] == -12
    raw['parameters'][0]['minimum'] = -100
    values['mix'] = values['mix'].model_copy(
        update={'document': ArrangementDocument.model_validate(raw)}
    )
    with pytest.raises(ValueError, match='widen'):
        Composition('mix', values)


def test_worked_example_and_longer_tail_do_not_extend_recordings() -> None:
    root = Path('conformance/composition').resolve()
    values = {}
    for path in root.rglob('*.toml'):
        document = parse_document(path.read_text())
        references = (
            {
                n.definition.path: str((path.parent / n.definition.path).resolve())
                for n in document.body.nodes
            }
            if isinstance(document, ArrangementDocument)
            else {}
        )
        values[str(path)] = DefinitionRecord(document=document, references=references)
    identity = str(root / 'concert.toml')
    composition = Composition(identity, values)
    assert [e.event.kind for e in composition.performance_trace(480000)] == [
        'trigger',
        'release',
    ]
    raw = values[identity].document.model_dump()
    raw['ports'][0]['binding']['end'] = 576000
    raw['body']['clips'][2]['source_end'] = 576000
    values[identity] = values[identity].model_copy(
        update={'document': ArrangementDocument.model_validate(raw)}
    )
    longer = Composition(identity, values)
    assert longer.performance_trace(576000) == composition.performance_trace(480000)
    windows = longer.evaluation_windows(0, 576000)
    assert windows['root/rehearsal', 'desk'] == (0, 480000)
    assert windows['root/piano', 'audio'] == (0, 576000)
    assert [e.event.kind for e in longer.performance_trace(240000)] == ['trigger']


def test_event_fanout_keeps_receivers_independent() -> None:
    values = definitions()
    raw = values['mix'].document.model_dump()
    raw['body']['nodes'].append(
        {
            'id': 'second',
            'definition': {'path': 'piano.toml'},
            'parameters': {'level': -12},
        }
    )
    raw['body']['connections'].append(
        {
            'source': {'node': 'notes', 'port': 'notes'},
            'destination': {'node': 'second', 'port': 'performance'},
        }
    )
    raw['body']['clips'].append(
        dict(
            raw['body']['clips'][0],
            id='second',
            source={'node': 'second', 'port': 'audio'},
        )
    )
    values['mix'] = values['mix'].model_copy(
        update={'document': ArrangementDocument.model_validate(raw)}
    )
    composition = Composition('mix', values)
    trace = composition.performance_trace(96000)
    assert len(trace) == 4
    assert [e.event for e in trace if e.instance == 'root/piano'] == [
        e.event for e in trace if e.instance == 'root/second'
    ]
    assert composition.instances['root/second'].parameters == {'level': -12}
    assert composition.instances['root/piano'].parameters == {'level': -6}
