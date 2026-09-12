import json
from pathlib import Path

import pytest

from ufor import light_animation, lights, modulation
from ufor.arrangement import ArrangementScore
from ufor.automation import Automation, AutomationScore, Knot, TimelineCurve
from ufor.codec import parse_score, score_toml
from ufor.composition import Composition, ScoreRecord
from ufor.control import Scope
from ufor.interface import (
    ControlBinding,
    ControlType,
    LightBinding,
    Output,
    OutputSelection,
    ParameterExport,
    Part,
    ScoreVersion,
)
from ufor.modulation import Target, Unit
from ufor.samples.instrument import InstrumentScore
from ufor.sequence import SequenceScore
from ufor.time import Rate, Timebase


def scores() -> dict[str, ScoreRecord]:
    piano = json.loads(Path('conformance/instrument.json').read_text())
    output = next(p for p in piano['outputs'])['stream']
    piano['body']['instrument']['modulation']['parameters'] = [
        {
            'target': {'name': 'processing', 'parameter': 'volume_db'},
            'unit': 'db',
            'scope': 'voice',
            'minimum': -60,
            'maximum': 6,
            'default': 0,
        }
    ]
    piano['parameters'] = [
        {'name': 'level', 'binding': {'name': 'processing', 'parameter': 'volume_db'}}
    ]
    notes = SequenceScore.model_validate(
        {
            'name': 'notes',
            'title': 'Notes',
            'timebases': [{'name': 'ticks', 'rate': {'numerator': 1000}}],
            'outputs': [
                {
                    'name': 'notes',
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
    mix = ArrangementScore.model_validate(
        {
            'name': 'mix',
            'title': 'Mix',
            'timebases': [{'name': 'output', 'rate': {'numerator': 48000}}],
            'outputs': [
                {
                    'name': 'main',
                    'stream': output,
                    'binding': {'track': 'mix', 'end': 96000},
                }
            ],
            'body': {
                'timebase': 'output',
                'parts': [
                    {'name': 'notes', 'score': {'path': 'notes.toml'}},
                    {
                        'name': 'piano',
                        'score': {'path': 'piano.toml'},
                        'parameters': {'level': -6},
                    },
                ],
                'connections': [
                    {
                        'source': {'name': 'notes', 'output': 'notes'},
                        'destination': {'name': 'piano', 'input': 'performance'},
                    }
                ],
                'tracks': [{'name': 'mix', 'stream': output}],
                'clips': [
                    {
                        'name': 'piano',
                        'source': {'name': 'piano', 'output': 'audio'},
                        'track': 'mix',
                        'source_start': 0,
                        'source_end': 96000,
                        'timeline_start': 0,
                    }
                ],
            },
        }
    )
    light_source = light_animation.AnimationScore(
        name='solid',
        title='Solid',
        timebases=[Timebase(name='frames', rate=Rate(numerator=48000))],
        outputs=[
            Output(
                name='light',
                stream=lights.LightType(
                    timebase='frames', components=['white'], layout=lights.strip(1)
                ),
                binding=LightBinding(),
            )
        ],
        body=light_animation.Animation(operation=light_animation.Fill(values=[1])),
    )
    target = Target(name='animation', parameter='amount')
    light = light_animation.AnimationScore(
        name='light',
        title='Light',
        timebases=[Timebase(name='frames', rate=Rate(numerator=48000))],
        outputs=[
            Output(
                name='light',
                stream=lights.LightType(
                    timebase='frames', components=['white'], layout=lights.strip(1)
                ),
                binding=LightBinding(),
            )
        ],
        parameters=[ParameterExport(name='brightness', binding=target)],
        body=light_animation.Animation(
            operation=light_animation.Gain(
                source=OutputSelection(name='solid', output='light')
            ),
            parts=[Part(name='solid', score=ScoreVersion(path='solid.toml'))],
            modulation=modulation.Modulation(
                parameters=[
                    modulation.Parameter(
                        target=target,
                        unit=Unit.ratio,
                        scope=Scope.part,
                        minimum=0,
                        maximum=2,
                        default=1,
                    )
                ]
            ),
        ),
    )
    fade = AutomationScore(
        name='fade',
        title='Light fade',
        timebases=[Timebase(name='milliseconds', rate=Rate(numerator=1000))],
        outputs=[
            Output(
                name='control',
                stream=ControlType(
                    timebase='milliseconds',
                    quantity='gain',
                    unit=Unit.ratio,
                    scope=Scope.part,
                ),
                binding=ControlBinding(),
            )
        ],
        body=Automation(
            target=Target(name='light', parameter='brightness'),
            scope=Scope.part,
            quantity='gain',
            unit=Unit.ratio,
            default=0,
            curves=[
                TimelineCurve(
                    name='fade',
                    unit=Unit.ratio,
                    knots=[Knot(tick=0, value=0), Knot(tick=2000, value=1)],
                )
            ],
        ),
    )
    return {
        'mix': ScoreRecord(
            score=mix, paths={'notes.toml': 'notes', 'piano.toml': 'piano'}
        ),
        'notes': ScoreRecord(score=notes),
        'piano': ScoreRecord(score=InstrumentScore.model_validate(piano)),
        'light': ScoreRecord(score=light, paths={'solid.toml': 'solid'}),
        'solid': ScoreRecord(score=light_source),
        'fade': ScoreRecord(score=fade),
    }


def test_sequence_drives_an_independently_configured_instrument() -> None:
    values = scores()
    composition = Composition('mix', values)
    assert composition.parts['root/piano'].parameters == {'level': -6}
    trace = composition.performance_trace(96000)
    assert [(e.part, e.event.kind, e.event.tick) for e in trace] == [
        ('root/piano', 'trigger', 480),
        ('root/piano', 'release', 43200),
    ]
    assert composition.performance_trace(96000, start=48000) == trace
    assert parse_score(score_toml(values['mix'].score)) == values['mix'].score


def test_arrangement_requests_reusable_control_with_audio_and_events() -> None:
    values = scores()
    control_case = json.loads(
        (Path(__file__).parents[1] / 'conformance/control-clips.json').read_text()
    )
    recording = parse_score(
        (
            Path(__file__).parents[1]
            / 'conformance/composition/recordings/rehearsal.toml'
        ).read_text()
    )
    raw = values['mix'].score.model_dump()
    raw['body']['parts'] += [
        {'name': 'take', 'score': {'path': 'take.toml'}},
        {'name': 'light', 'score': {'path': 'light.toml'}},
        {'name': 'fade', 'score': {'path': 'fade.toml'}},
    ]
    raw['body']['clips'].append(
        {
            'name': 'recorded-take',
            'source': {'name': 'take', 'output': 'desk'},
            'track': 'mix',
            'source_start': 0,
            'source_end': 96000,
            'timeline_start': 0,
        }
    )
    raw['body']['control_clips'] = [
        {
            'name': 'light-fade',
            'source': {'name': 'fade', 'output': 'control'},
            'source_start': control_case['source_interval'][0],
            'source_end': control_case['source_interval'][1],
            'timeline_start': control_case['timeline_start'],
        }
    ]
    values['mix'] = ScoreRecord(
        score=ArrangementScore.model_validate(raw),
        paths={
            'notes.toml': 'notes',
            'piano.toml': 'piano',
            'take.toml': 'take',
            'light.toml': 'light',
            'fade.toml': 'fade',
        },
    )
    values['take'] = ScoreRecord(score=recording)
    composition = Composition('mix', values)
    windows = composition.evaluation_windows(*control_case['requested_timeline'])
    assert windows['root/fade', 'control'] == tuple(control_case['requested_source'])
    assert windows['root/piano', 'audio'] == (0, 96000)
    assert windows['root/take', 'desk'] == (0, 96000)
    assert [event.event.kind for event in composition.performance_trace(96000)] == [
        'trigger',
        'release',
    ]


@pytest.mark.parametrize(
    ('change', 'message'),
    [
        ('wrong-source', 'source is not automation'),
        ('unknown-target', 'unknown automation target'),
        ('duplicate-target', 'competing automation target'),
        ('inexact-rate', 'integer tick'),
    ],
)
def test_control_clips_reject_ambiguous_or_unrepresentable_mappings(
    change: str, message: str
) -> None:
    values = scores()
    raw = values['mix'].score.model_dump()
    raw['body']['parts'] += [
        {'name': 'light', 'score': {'path': 'light.toml'}},
        {'name': 'fade', 'score': {'path': 'fade.toml'}},
    ]
    clip = {
        'name': 'light-fade',
        'source': {'name': 'fade', 'output': 'control'},
        'source_start': 0,
        'source_end': 2000,
        'timeline_start': 0,
    }
    raw['body']['control_clips'] = [clip]
    if change == 'wrong-source':
        clip['source'] = {'name': 'notes', 'output': 'notes'}
    elif change == 'unknown-target':
        auto = values['fade'].score.model_copy(
            update={
                'body': values['fade'].score.body.model_copy(
                    update={'target': Target(name='missing', parameter='brightness')}
                )
            }
        )
        values['fade'] = ScoreRecord(score=auto)
    elif change == 'duplicate-target':
        raw['body']['control_clips'].append(clip | {'name': 'second-fade'})
    elif change == 'inexact-rate':
        auto_data = values['fade'].score.model_dump()
        auto_data['timebases'][0]['rate']['numerator'] = 1001
        values['fade'] = ScoreRecord(score=AutomationScore.model_validate(auto_data))
        clip['source_end'] = 1
    values['mix'] = ScoreRecord(
        score=ArrangementScore.model_validate(raw),
        paths={
            'notes.toml': 'notes',
            'piano.toml': 'piano',
            'light.toml': 'light',
            'fade.toml': 'fade',
        },
    )
    with pytest.raises(ValueError, match=message):
        Composition('mix', values)


def test_cropped_nested_instances_replay_their_own_histories() -> None:
    values = scores()
    mix = values['mix'].score
    raw = mix.model_dump()
    raw['body']['parts'] = [
        {'name': n, 'score': {'path': 'mix.toml'}} for n in ('first', 'second')
    ]
    raw['body']['connections'] = []
    raw['body']['clips'] = [
        {
            'name': n,
            'source': {'name': n, 'output': 'main'},
            'track': 'mix',
            'source_start': 48000,
            'source_end': 96000,
            'timeline_start': 0,
        }
        for n in ('first', 'second')
    ]
    raw['outputs'][0]['binding']['end'] = 48000
    values['outer'] = ScoreRecord(
        score=ArrangementScore.model_validate(raw), paths={'mix.toml': 'mix'}
    )
    composition = Composition('outer', values)
    assert composition.evaluation_windows(0, 48000)[('root/first/piano', 'audio')] == (
        48000,
        96000,
    )
    trace = composition.performance_trace(48000)
    assert len(trace) == 4
    assert {e.part for e in trace} == {'root/first/piano', 'root/second/piano'}
    assert composition.performance_trace(48000) == trace


@pytest.mark.parametrize(
    'change, message',
    [
        ('missing', 'Missing|missing'),
        ('private', 'unknown public output'),
        ('parameter', 'unknown public parameters'),
        ('range', 'outside public range'),
        ('cycle', 'cycle'),
        ('pin', 'digest'),
    ],
)
def test_resolution_rejects_invalid_references_and_configuration(
    change: str, message: str
) -> None:
    values = scores()
    raw = values['mix'].score.model_dump()
    if change == 'missing':
        del values['piano']
    elif change == 'private':
        raw['body']['clips'][0]['source']['output'] = 'private'
    elif change == 'parameter':
        raw['body']['parts'][1]['parameters'] = {'private': 0}
    elif change == 'range':
        raw['body']['parts'][1]['parameters'] = {'level': 20}
    elif change == 'cycle':
        values['mix'] = values['mix'].model_copy(
            update={'paths': {'notes.toml': 'mix', 'piano.toml': 'piano'}}
        )
    elif change == 'pin':
        raw['body']['parts'][1]['score']['sha256'] = 'f' * 64
    if change != 'cycle':
        values['mix'] = values['mix'].model_copy(
            update={'score': ArrangementScore.model_validate(raw)}
        )
    with pytest.raises(ValueError, match=message):
        Composition('mix', values)


def test_unrepresentable_event_ticks_and_missing_pitch_are_rejected() -> None:
    for bad_clock in (True, False):
        values = scores()
        raw = values['notes'].score.model_dump()
        if bad_clock:
            raw['timebases'][0]['rate']['numerator'] = 1001
        else:
            raw['body']['events'][0]['pitch_hz'] = None
        values['notes'] = ScoreRecord(score=SequenceScore.model_validate(raw))
        with pytest.raises(ValueError, match='integer tick|pitch_hz'):
            Composition('mix', values)


def test_parent_parameter_inherits_child_configuration_and_can_narrow_it() -> None:
    values = scores()
    raw = values['mix'].score.model_dump()
    raw['parameters'] = [
        {
            'name': 'volume',
            'binding': {'name': 'piano', 'parameter': 'level'},
            'minimum': -30,
            'maximum': 0,
        }
    ]
    values['mix'] = values['mix'].model_copy(
        update={'score': ArrangementScore.model_validate(raw)}
    )
    composition = Composition('mix', values, {'volume': -12})
    assert composition.parameter_contract('mix', 'volume').default == -6
    assert composition.parts['root/piano'].parameters['level'] == -12
    raw['parameters'][0]['minimum'] = -100
    values['mix'] = values['mix'].model_copy(
        update={'score': ArrangementScore.model_validate(raw)}
    )
    with pytest.raises(ValueError, match='widen'):
        Composition('mix', values)


def test_worked_example_and_longer_tail_do_not_extend_recordings() -> None:
    root = Path('conformance/composition').resolve()
    values = {}
    for path in root.rglob('*.toml'):
        score = parse_score(path.read_text())
        paths = (
            {
                n.score.path: str((path.parent / n.score.path).resolve())
                for n in score.body.parts
            }
            if isinstance(score, ArrangementScore)
            else {}
        )
        values[str(path)] = ScoreRecord(score=score, paths=paths)
    identity = str(root / 'concert.toml')
    composition = Composition(identity, values)
    assert [e.event.kind for e in composition.performance_trace(480000)] == [
        'trigger',
        'release',
    ]
    raw = values[identity].score.model_dump()
    raw['outputs'][0]['binding']['end'] = 576000
    raw['body']['clips'][2]['source_end'] = 576000
    values[identity] = values[identity].model_copy(
        update={'score': ArrangementScore.model_validate(raw)}
    )
    longer = Composition(identity, values)
    assert longer.performance_trace(576000) == composition.performance_trace(480000)
    windows = longer.evaluation_windows(0, 576000)
    assert windows['root/rehearsal', 'desk'] == (0, 480000)
    assert windows['root/piano', 'audio'] == (0, 576000)
    assert [e.event.kind for e in longer.performance_trace(240000)] == ['trigger']


def test_event_fanout_keeps_receivers_independent() -> None:
    values = scores()
    raw = values['mix'].score.model_dump()
    raw['body']['parts'].append(
        {
            'name': 'second',
            'score': {'path': 'piano.toml'},
            'parameters': {'level': -12},
        }
    )
    raw['body']['connections'].append(
        {
            'source': {'name': 'notes', 'output': 'notes'},
            'destination': {'name': 'second', 'input': 'performance'},
        }
    )
    raw['body']['clips'].append(
        dict(
            raw['body']['clips'][0],
            name='second',
            source={'name': 'second', 'output': 'audio'},
        )
    )
    values['mix'] = values['mix'].model_copy(
        update={'score': ArrangementScore.model_validate(raw)}
    )
    composition = Composition('mix', values)
    trace = composition.performance_trace(96000)
    assert len(trace) == 4
    assert [e.event for e in trace if e.part == 'root/piano'] == [
        e.event for e in trace if e.part == 'root/second'
    ]
    assert composition.parts['root/second'].parameters == {'level': -12}
    assert composition.parts['root/piano'].parameters == {'level': -6}


def test_forwarded_input_and_output_can_share_a_name() -> None:
    values = scores()
    piano = values['piano'].score
    raw = piano.model_dump()
    raw['inputs'][0]['name'] = 'audio'
    values['piano'] = ScoreRecord(score=InstrumentScore.model_validate(raw))
    wrapper = ArrangementScore.model_validate(
        {
            'name': 'wrapper',
            'title': 'Wrapped piano',
            'timebases': [
                t for t in piano.timebases if t.name == piano.outputs[0].stream.timebase
            ],
            'inputs': [
                {
                    'name': 'audio',
                    'stream': piano.inputs[0].stream,
                    'binding': {'name': 'inside', 'input': 'audio'},
                }
            ],
            'outputs': [
                {
                    'name': 'audio',
                    'stream': piano.outputs[0].stream,
                    'binding': {'name': 'inside', 'output': 'audio'},
                }
            ],
            'body': {
                'timebase': piano.outputs[0].stream.timebase,
                'parts': [{'name': 'inside', 'score': {'path': 'piano.toml'}}],
            },
        }
    )
    values['wrapper'] = ScoreRecord(score=wrapper, paths={'piano.toml': 'piano'})
    raw = values['mix'].score.model_dump()
    raw['body']['parts'][1]['parameters'] = {}
    raw['body']['connections'][0]['destination']['input'] = 'audio'
    values['mix'] = ScoreRecord(
        score=ArrangementScore.model_validate(raw),
        paths={'notes.toml': 'notes', 'piano.toml': 'wrapper'},
    )
    composition = Composition('mix', values)
    deliveries = composition.performance_trace(96000)
    assert [d.part for d in deliveries] == ['root/piano/inside', 'root/piano/inside']
    assert [d.input for d in deliveries] == ['audio', 'audio']
    assert [d.event.tick for d in deliveries] == [480, 43200]


def test_score_version_accepts_an_optional_hash_but_not_old_selections() -> None:
    from ufor.interface import InputSelection, OutputSelection, ScoreVersion

    assert ScoreVersion(path='piano.toml').sha256 is None
    assert ScoreVersion(path='piano.toml', sha256='a' * 64).sha256 == 'a' * 64
    with pytest.raises(ValueError):
        InputSelection.model_validate({'name': 'piano', 'output': 'audio'})
    with pytest.raises(ValueError):
        OutputSelection.model_validate({'node': 'piano', 'port': 'audio'})
