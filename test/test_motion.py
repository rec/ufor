from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.codec import parse_score, score_toml
from ufor.library_files import read_library
from ufor.motion import (
    Affine,
    Contour,
    Cycle,
    EnterStage,
    FinishStage,
    Hold,
    Marker,
    MotionEvent,
    MotionParameter,
    MotionScore,
    MotionState,
    MotionUse,
    ParameterReference,
    Patch,
    PlaybackMode,
    Product,
    SampleHold,
    SampleHoldState,
    Stage,
    Stages,
    StageTransition,
    Sum,
    advance_motion,
    contour_envelope,
    initial_motion,
    instantiate_motion,
    motion_at,
    motion_event,
    transform_value,
)
from ufor.samples.processing import ReleaseTiming, SoundSettings
from ufor.segments import Segment


def staged_motion() -> MotionUse:
    return MotionUse(
        body=Stages(
            initial_stage='waiting',
            stages=[
                Stage(name='waiting', motion=Hold(value=0.0)),
                Stage(
                    name='attack',
                    motion=Contour(
                        initial='current',
                        segments=[Segment(duration=Fraction(1, 4), to=0.7)],
                    ),
                ),
                Stage(
                    name='sway',
                    motion=Cycle(
                        rate=Fraction(2),
                        center=0.7,
                        depth=0.2,
                        markers=[Marker(name='peak', position=Fraction(1, 4))],
                    ),
                ),
                Stage(
                    name='release',
                    motion=Contour(
                        initial='current',
                        segments=[Segment(duration=Fraction(1, 4), to=0.0)],
                    ),
                ),
            ],
            transitions=[
                StageTransition(
                    from_stages=['waiting', 'attack', 'sway', 'release'],
                    event='note_on',
                    action=EnterStage(stage='attack'),
                ),
                StageTransition(
                    from_stages=['attack'],
                    event='stage.done',
                    action=EnterStage(stage='sway'),
                ),
                StageTransition(
                    from_stages=['attack', 'sway'],
                    event='note_off',
                    action=EnterStage(stage='release'),
                ),
                StageTransition(
                    from_stages=['release'],
                    event='stage.done',
                    action=FinishStage(),
                ),
                StageTransition(
                    from_stages=['waiting'],
                    event='cue.sway',
                    action=EnterStage(stage='sway'),
                ),
            ],
        )
    )


def test_stage_contour_durations_match_the_motion_clock() -> None:
    body = {
        'kind': 'stages',
        'initial_stage': 'attack',
        'stages': [
            {
                'name': 'attack',
                'motion': {
                    'kind': 'contour',
                    'segments': [{'duration': '1 beat', 'to': 1}],
                },
            }
        ],
    }
    motion = MotionUse.model_validate({'clock': 'beats', 'body': body})
    assert motion.clock.value == 'beats'
    with pytest.raises(ValidationError, match='stage contour segment units'):
        MotionUse.model_validate({'clock': 'seconds', 'body': body})


def test_transport_position_cycle_follows_song_beats_across_seek() -> None:
    motion = MotionUse.model_validate(
        {
            'clock': 'beats',
            'position_driver': 'transport',
            'body': {
                'kind': 'cycle',
                'shape': 'triangle',
                'rate': '1/4',
                'reset': 'transport',
            },
        }
    )
    state = initial_motion(motion, Fraction(0))
    assert motion_at(motion, state, Fraction(0)).value == -1
    assert motion_at(motion, state, Fraction(1)).value == 0
    assert motion_at(motion, state, Fraction(2)).value == 1
    assert motion_at(motion, state, Fraction(1)).value == 0
    with pytest.raises(ValueError, match='does not accept phase commands'):
        motion_event(
            motion, state, MotionEvent(at=Fraction(1), ordinal=0, action='reset')
        )
    with pytest.raises(ValidationError, match='transport position requires'):
        MotionUse.model_validate(
            {
                'clock': 'beats',
                'position_driver': 'transport',
                'body': {'kind': 'cycle', 'rate': '1'},
            }
        )
    reference = MotionUse.model_validate(
        {
            'clock': 'beats',
            'position_driver': 'transport',
            'score': {'selector': 'pulse'},
        }
    )
    score = MotionScore(
        name='pulse',
        title='Pulse',
        body=Cycle(rate=Fraction(1, 4), reset='transport'),
    )
    resolved = instantiate_motion(
        score, clock=reference.clock, position_driver=reference.position_driver
    )
    assert resolved.position_driver == reference.position_driver


def test_voice_motion_event_connections_validate_ports_and_cues() -> None:
    source = staged_motion()
    destination = MotionUse(
        body=Stages(
            initial_stage='waiting',
            stages=[
                Stage(name='waiting', motion=Hold(value=0.0)),
                Stage(name='bright', motion=Hold(value=1.0)),
            ],
            transitions=[
                StageTransition(
                    from_stages=['waiting'],
                    event='cue.brighten',
                    action=EnterStage(stage='bright'),
                )
            ],
        )
    )
    raw = {
        'motions': {
            'source': source.model_dump(),
            'destination': destination.model_dump(),
        },
        'modulation': {
            'sources': [
                {'name': 'source', 'scope': 'voice', 'minimum': -1, 'maximum': 1},
                {'name': 'destination', 'scope': 'voice', 'minimum': -1, 'maximum': 1},
            ]
        },
        'bindings': [
            {'name': 'source', 'kind': 'motion', 'reference': 'source'},
            {'name': 'destination', 'kind': 'motion', 'reference': 'destination'},
        ],
        'event_connections': [
            {
                'source': 'source',
                'port': 'peak',
                'destination': 'destination',
                'cue': 'brighten',
            }
        ],
    }
    assert SoundSettings.model_validate(raw).event_connections[0].port == 'peak'
    raw['event_connections'][0]['port'] = 'stage.missing'
    with pytest.raises(ValidationError, match='unknown port'):
        SoundSettings.model_validate(raw)
    raw['motions']['source']['body']['stages'][2]['motion'] = {
        'kind': 'contour',
        'segments': [{'duration': '1 s', 'to': 1}],
        'markers': [{'name': 'peak', 'position': '1/2'}],
        'playback': 'loop',
    }
    raw['event_connections'][0]['port'] = 'cycle'
    assert SoundSettings.model_validate(raw).event_connections[0].port == 'cycle'
    raw['event_connections'][0]['port'] = 'turned'
    with pytest.raises(ValidationError, match='unknown port'):
        SoundSettings.model_validate(raw)
    raw['motions']['source']['body']['stages'][2]['motion']['playback'] = 'ping_pong'
    assert SoundSettings.model_validate(raw).event_connections[0].port == 'turned'


def test_named_contour_release_timing_is_explicit_and_contour_only() -> None:
    raw = {
        'motions': {
            'motion': {
                'body': {
                    'kind': 'contour',
                    'segments': [{'duration': '1 s', 'to': 1}],
                    'release': [{'duration': '1 s', 'to': 0}],
                }
            }
        },
        'modulation': {
            'sources': [
                {'name': 'motion', 'scope': 'voice', 'minimum': 0, 'maximum': 1}
            ]
        },
        'bindings': [{'name': 'motion', 'kind': 'motion', 'reference': 'motion'}],
    }
    default = SoundSettings.model_validate(raw)
    assert default.bindings[0].release_timing == ReleaseTiming.event
    raw['bindings'][0]['release_timing'] = 'voice'
    selected = SoundSettings.model_validate(raw)
    assert selected.bindings[0].release_timing == ReleaseTiming.voice
    assert SoundSettings.model_validate_json(selected.model_dump_json()) == selected
    raw['motions']['motion']['body']['release'] = []
    with pytest.raises(ValidationError, match='releasing contour'):
        SoundSettings.model_validate(raw)
    raw['motions']['motion']['body'] = {'kind': 'cycle', 'rate': '1'}
    raw['modulation']['sources'][0]['minimum'] = -1
    with pytest.raises(ValidationError, match='releasing contour'):
        SoundSettings.model_validate(raw)


def test_sample_hold_draws_only_on_sample_events_and_restores_its_stream() -> None:
    motion = MotionUse(body=SampleHold(minimum=0.2, maximum=0.8))
    state = initial_motion(motion, Fraction(0), seed=123)
    assert isinstance(state.runtime, SampleHoldState)
    first = motion_at(motion, state, Fraction(10))
    assert 0.2 <= first.value < 0.8
    assert first.weight == 1
    for i, fields in enumerate(
        [
            {'action': 'note_on'},
            {'action': 'note_off'},
            {'action': 'reverse'},
            {'action': 'seek', 'position': '1/4'},
            {'action': 'pause'},
            {'action': 'resume'},
        ]
    ):
        state = motion_event(
            motion,
            state,
            MotionEvent.model_validate({'at': str(i), 'ordinal': 0, **fields}),
        )
        assert motion_at(motion, state, Fraction(i)).value == first.value
    snapshot = MotionState.model_validate_json(state.model_dump_json())
    event = MotionEvent(at=Fraction(6), ordinal=0, action='sample')
    second = motion_event(motion, state, event)
    assert motion_at(motion, second, Fraction(6)).value != first.value
    assert motion_event(motion, snapshot, event) == second
    assert initial_motion(motion, Fraction(0), seed=123) != initial_motion(
        motion, Fraction(0), seed=124
    )


def test_patch_sample_commands_select_only_sample_hold_children() -> None:
    patch = Patch.model_validate(
        {
            'motions': {
                'clock': {
                    'kind': 'cycle',
                    'rate': '1',
                    'markers': [{'name': 'pulse', 'position': '1/2'}],
                },
                'random': {'kind': 'sample_hold'},
            },
            'outputs': {'value': 'random'},
            'events': [
                {
                    'source': 'clock.pulse',
                    'target': 'random',
                    'action': 'sample',
                    'every': 3,
                    'offset': 1,
                    'probability': 0.5,
                    'delay': '1/8',
                }
            ],
        }
    )
    assert Patch.model_validate_json(patch.model_dump_json()) == patch
    score = MotionScore(name='random', title='Random', body=patch)
    assert parse_score(score_toml(score)) == score
    raw = patch.model_dump(mode='json')
    raw['events'][0]['target'] = 'clock'
    with pytest.raises(ValidationError, match='sample target'):
        Patch.model_validate(raw)
    with pytest.raises(ValidationError, match='voice scope'):
        MotionUse(body=patch, scope='instrument')
    with pytest.raises(ValidationError, match='minimum'):
        SampleHold(minimum=0.5, maximum=0.25)


def test_sample_hold_with_equal_bounds_is_constant_but_advances_draws() -> None:
    motion = MotionUse(body=SampleHold(minimum=0.5, maximum=0.5))
    initial = initial_motion(motion, Fraction(0))
    sampled = motion_event(
        motion, initial, MotionEvent(at=Fraction(1), ordinal=0, action='sample')
    )
    assert initial.runtime != sampled.runtime
    assert motion_at(motion, sampled, Fraction(1)).value == 0.5


def test_patch_transforms_follow_dependencies_without_clipping() -> None:
    patch = Patch(
        motions={
            'output': Affine(input='combined', scale=-0.5, offset=0.25),
            'combined': Sum(inputs=['shaped', 'carrier']),
            'shaped': Product(inputs=['carrier', 'envelope']),
            'carrier': Cycle(rate=1),
            'envelope': Contour(segments=[Segment(duration=1, to=1)]),
        },
        outputs={'signal': 'output'},
    )
    values = {'carrier': 1.0, 'envelope': 0.5}
    for name in patch.signal_order:
        if isinstance(body := patch.motions[name], (Sum, Product, Affine)):
            values[name] = transform_value(body, values)
    assert values['combined'] == 1.5
    assert values['output'] == -0.5
    assert patch.signal_ranges['output'] == (-0.75, 1.25)
    assert Patch.model_validate_json(patch.model_dump_json()) == patch


@pytest.mark.parametrize(
    ('inputs', 'message'),
    [(['missing', 'carrier'], 'unknown child'), (['output', 'carrier'], 'cycle')],
)
def test_patch_transform_dependencies_are_validated(
    inputs: list[str], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Patch(
            motions={'carrier': Cycle(rate=1), 'output': Sum(inputs=inputs)},
            outputs={'signal': 'output'},
        )


def test_patch_transformed_output_requires_a_covering_source_domain() -> None:
    raw = {
        'motions': {
            'patch': {
                'body': {
                    'kind': 'patch',
                    'motions': {
                        'cycle': {'kind': 'cycle', 'rate': '1'},
                        'sum': {'kind': 'sum', 'inputs': ['cycle', 'cycle']},
                    },
                    'outputs': {'signal': 'sum'},
                }
            }
        },
        'bindings': [
            {
                'name': 'signal',
                'kind': 'motion',
                'reference': 'patch',
                'output': 'signal',
            }
        ],
        'modulation': {
            'sources': [
                {'name': 'signal', 'scope': 'voice', 'minimum': -2, 'maximum': 2}
            ]
        },
    }
    assert SoundSettings.model_validate(raw)
    raw['modulation']['sources'][0]['maximum'] = 1
    with pytest.raises(ValidationError, match='exceeds its declared source domain'):
        SoundSettings.model_validate(raw)


def test_patch_named_outputs_select_child_signal_domains() -> None:
    raw = {
        'motions': {
            'gesture': {
                'body': {
                    'kind': 'patch',
                    'motions': {
                        'amp': {
                            'kind': 'contour',
                            'segments': [{'duration': '1 s', 'to': 1}],
                        },
                        'vibrato': {'kind': 'cycle', 'rate': '5'},
                    },
                    'outputs': {'level': 'amp', 'pitch': 'vibrato'},
                }
            }
        },
        'modulation': {
            'sources': [
                {'name': 'level', 'scope': 'voice', 'minimum': 0, 'maximum': 1},
                {'name': 'pitch', 'scope': 'voice', 'minimum': -1, 'maximum': 1},
            ]
        },
        'bindings': [
            {
                'name': 'level',
                'kind': 'motion',
                'reference': 'gesture',
                'output': 'level',
            },
            {
                'name': 'pitch',
                'kind': 'motion',
                'reference': 'gesture',
                'output': 'pitch',
            },
        ],
    }
    settings = SoundSettings.model_validate(raw)
    assert SoundSettings.model_validate_json(settings.model_dump_json()) == settings
    raw['bindings'][1]['output'] = 'missing'
    with pytest.raises(ValidationError, match='requires a named output'):
        SoundSettings.model_validate(raw)
    raw['bindings'][1]['output'] = 'pitch'
    raw['modulation']['sources'][0]['minimum'] = -1
    with pytest.raises(ValidationError, match='source scope and domain'):
        SoundSettings.model_validate(raw)
    raw['modulation']['sources'][0]['minimum'] = 0
    raw['modulation']['sources'][1]['minimum'] = 0
    raw['motions']['gesture']['body']['outputs']['pitch'] = 'amp'
    raw['motions']['gesture']['body']['motions']['amp']['release'] = [
        {'duration': '1 s', 'to': 0}
    ]
    assert SoundSettings.model_validate(raw)
    raw['bindings'][1]['release_timing'] = 'voice'
    with pytest.raises(ValidationError, match='one release timing'):
        SoundSettings.model_validate(raw)


def test_patch_output_and_clock_references_are_validated() -> None:
    body = {
        'kind': 'patch',
        'motions': {
            'amp': {
                'kind': 'contour',
                'segments': [{'duration': '1 beat', 'to': 1}],
            }
        },
        'outputs': {'level': 'amp'},
    }
    score = MotionScore.model_validate(
        {'name': 'gesture', 'title': 'Gesture', 'body': body}
    )
    assert parse_score(score_toml(score)) == score
    assert isinstance(MotionUse(clock='beats', body=score.body).body, type(score.body))
    with pytest.raises(ValidationError, match='patch contour segment units'):
        MotionUse(body=score.body)
    body['outputs']['level'] = 'missing'
    with pytest.raises(ValidationError, match='unknown child Motion'):
        MotionScore.model_validate(
            {'name': 'gesture', 'title': 'Gesture', 'body': body}
        )


def test_patch_marker_can_start_waiting_contour() -> None:
    body = {
        'kind': 'patch',
        'motions': {
            'clock': {
                'kind': 'cycle',
                'rate': '2',
                'markers': [{'name': 'peak', 'position': '1/4'}],
            },
            'accent': {
                'kind': 'contour',
                'start': 'event',
                'segments': [{'duration': '1/4 s', 'to': 1}],
            },
        },
        'events': [{'source': 'clock.peak', 'target': 'accent', 'action': 'start'}],
        'outputs': {'value': 'accent'},
    }
    score = MotionScore.model_validate(
        {'name': 'accent', 'title': 'Accent', 'body': body}
    )
    assert parse_score(score_toml(score)) == score
    contour = MotionUse(body=score.body.motions['accent'])
    state = initial_motion(contour, Fraction(0))
    assert motion_at(contour, state, Fraction(1)).value == 0
    state = motion_event(
        contour,
        state,
        MotionEvent(at=Fraction(1, 8), ordinal=0, action='start'),
    )
    assert motion_at(contour, state, Fraction(1, 4)).value == 0.5
    body['events'][0]['every'] = 3
    body['events'][0]['offset'] = 2
    body['events'][0]['probability'] = 0.5
    body['events'][0]['delay'] = '1/64'
    divided = MotionScore.model_validate(
        {'name': 'accent', 'title': 'Accent', 'body': body}
    )
    assert parse_score(score_toml(divided)) == divided
    for every in (0, -1, 1.5, True):
        body['events'][0]['every'] = every
        with pytest.raises(ValidationError):
            MotionScore.model_validate(
                {'name': 'accent', 'title': 'Accent', 'body': body}
            )
    body['events'][0]['every'] = 1
    for offset in (-1, 1.5, True):
        body['events'][0]['offset'] = offset
        with pytest.raises(ValidationError):
            MotionScore.model_validate(
                {'name': 'accent', 'title': 'Accent', 'body': body}
            )
    body['events'][0]['offset'] = 4
    MotionScore.model_validate({'name': 'accent', 'title': 'Accent', 'body': body})
    body['events'][0]['offset'] = 0
    body['events'][0]['source'] = 'clock.missing'
    with pytest.raises(ValidationError, match='unknown marker'):
        MotionScore.model_validate({'name': 'accent', 'title': 'Accent', 'body': body})
    body['events'][0]['source'] = 'clock.peak'
    body['motions']['accent']['start'] = 'activation'
    with pytest.raises(ValidationError, match='event-start Contour'):
        MotionScore.model_validate({'name': 'accent', 'title': 'Accent', 'body': body})
    body['motions']['accent']['start'] = 'event'
    body['motions']['accent']['retrigger'] = 'reset'
    with pytest.raises(ValidationError, match='event-start Contour'):
        MotionScore.model_validate({'name': 'accent', 'title': 'Accent', 'body': body})
    with pytest.raises(ValidationError, match='stage contours start on stage entry'):
        Stages.model_validate(
            {
                'initial_stage': 'accent',
                'stages': [
                    {
                        'name': 'accent',
                        'motion': {
                            'kind': 'contour',
                            'start': 'event',
                            'segments': [{'duration': '1 s', 'to': 1}],
                        },
                    }
                ],
            }
        )


def test_patch_marker_cues_child_stages() -> None:
    body = {
        'kind': 'patch',
        'motions': {
            'clock': {
                'kind': 'cycle',
                'rate': '2',
                'markers': [{'name': 'peak', 'position': '1/4'}],
            },
            'level': {
                'kind': 'stages',
                'initial_stage': 'waiting',
                'stages': [
                    {'name': 'waiting', 'motion': {'kind': 'hold'}},
                    {'name': 'bright', 'motion': {'kind': 'hold', 'value': 1}},
                ],
                'transitions': [
                    {
                        'from': ['waiting'],
                        'event': 'cue.brighten',
                        'action': {'kind': 'enter', 'stage': 'bright'},
                    }
                ],
            },
        },
        'outputs': {'value': 'level'},
        'events': [
            {
                'source': 'clock.peak',
                'target': 'level',
                'action': 'cue',
                'cue': 'brighten',
            }
        ],
    }
    score = MotionScore.model_validate(
        {'name': 'gesture', 'title': 'Gesture', 'body': body}
    )
    assert parse_score(score_toml(score)) == score
    body['events'][0]['cue'] = 'missing'
    with pytest.raises(ValidationError, match='matching stage transition'):
        MotionUse.model_validate({'body': body})
    body['events'][0].pop('cue')
    with pytest.raises(ValidationError, match='require a cue name'):
        MotionUse.model_validate({'body': body})


@pytest.mark.parametrize('source_kind', ['marker', 'stage.done'])
def test_patch_stage_event_commands_children(source_kind: str) -> None:
    port = 'peak' if source_kind == 'marker' else 'stage.done'
    clock = {
        'kind': 'stages',
        'initial_stage': 'playing',
        'stages': [
            {
                'name': 'playing',
                'motion': {
                    'kind': 'cycle',
                    'rate': '2',
                    'markers': [{'name': 'peak', 'position': '1/4'}],
                }
                if source_kind == 'marker'
                else {
                    'kind': 'contour',
                    'segments': [{'duration': '1/4 s', 'to': 1}],
                },
            }
        ],
    }
    body = {
        'kind': 'patch',
        'motions': {
            'clock': clock,
            'level': {
                'kind': 'stages',
                'initial_stage': 'waiting',
                'stages': [
                    {'name': 'waiting', 'motion': {'kind': 'hold'}},
                    {'name': 'bright', 'motion': {'kind': 'hold', 'value': 1}},
                ],
                'transitions': [
                    {
                        'from': ['waiting'],
                        'event': 'cue.brighten',
                        'action': {'kind': 'enter', 'stage': 'bright'},
                    }
                ],
            },
        },
        'outputs': {'value': 'level'},
        'events': [
            {
                'source': f'clock.{port}',
                'target': 'level',
                'action': 'cue',
                'cue': 'brighten',
            }
        ],
    }
    score = MotionScore.model_validate(
        {'name': 'gesture', 'title': 'Gesture', 'body': body}
    )
    assert parse_score(score_toml(score)) == score
    with pytest.raises(ValidationError, match='voice scope'):
        MotionUse.model_validate({'body': body, 'scope': 'part'})
    body['events'][0]['source'] = 'clock.missing'
    with pytest.raises(ValidationError, match='unknown stage event'):
        MotionUse.model_validate({'body': body})
    body['motions']['accent'] = {
        'kind': 'contour',
        'start': 'event',
        'segments': [{'duration': '1/4 s', 'to': 1}],
    }
    body['outputs'] = {'value': 'accent'}
    body['events'][0]['source'] = f'clock.{port}'
    body['events'][0]['target'] = 'accent'
    body['events'][0]['action'] = 'start'
    body['events'][0].pop('cue')
    score = MotionScore.model_validate(
        {'name': 'gesture', 'title': 'Gesture', 'body': body}
    )
    assert parse_score(score_toml(score)) == score
    body['motions']['accent']['start'] = 'activation'
    with pytest.raises(ValidationError, match='event-start Contour'):
        MotionUse.model_validate({'body': body})


@pytest.mark.parametrize('child_kind', ['cycle', 'stages'])
def test_patch_named_event_output_validates_child_port(child_kind: str) -> None:
    child = {
        'kind': 'cycle',
        'rate': '1',
        'markers': [{'name': 'peak', 'position': '1/4'}],
    }
    if child_kind == 'stages':
        child = {
            'kind': 'stages',
            'initial_stage': 'playing',
            'stages': [{'name': 'playing', 'motion': child}],
        }
    body = {
        'kind': 'patch',
        'motions': {'pulse': child},
        'outputs': {'signal': 'pulse'},
        'event_outputs': {'strike': 'pulse.peak'},
    }
    patch = MotionUse.model_validate({'body': body})
    assert MotionUse.model_validate_json(patch.model_dump_json()) == patch
    settings = {
        'motions': {
            'patch': {'body': body},
            'level': {
                'body': {
                    'kind': 'stages',
                    'initial_stage': 'waiting',
                    'stages': [
                        {'name': 'waiting', 'motion': {'kind': 'hold'}},
                        {'name': 'bright', 'motion': {'kind': 'hold', 'value': 1}},
                    ],
                    'transitions': [
                        {
                            'from': ['waiting'],
                            'event': 'cue.brighten',
                            'action': {'kind': 'enter', 'stage': 'bright'},
                        }
                    ],
                }
            },
        },
        'bindings': [
            {
                'name': 'patch',
                'kind': 'motion',
                'reference': 'patch',
                'output': 'signal',
            },
            {'name': 'level', 'kind': 'motion', 'reference': 'level'},
        ],
        'modulation': {
            'sources': [
                {'name': 'patch', 'scope': 'voice', 'minimum': -1, 'maximum': 1},
                {'name': 'level', 'scope': 'voice', 'minimum': -1, 'maximum': 1},
            ]
        },
        'event_connections': [
            {
                'source': 'patch',
                'port': 'strike',
                'destination': 'level',
                'cue': 'brighten',
            }
        ],
    }
    assert SoundSettings.model_validate(settings)
    if child_kind == 'stages':
        body['event_outputs']['strike'] = 'pulse.stage.done'
        assert MotionUse.model_validate({'body': body})
    body['event_outputs']['strike'] = 'pulse.missing'
    with pytest.raises(ValidationError, match='unknown child event'):
        MotionUse.model_validate({'body': body})


@pytest.mark.parametrize(
    ('body', 'expected'),
    [
        ('kind = "cycle"\nshape = "sine"\nrate = "5 Hz"', Cycle),
        (
            'kind = "contour"\ninitial = 0.0\n'
            'segments = [{ duration = "10 ms", to = 1.0 }]\n'
            'release = [{ duration = "200 ms", to = 0.0 }]',
            Contour,
        ),
    ],
)
def test_motion_score_round_trips_simple_bodies(
    body: str, expected: type[object]
) -> None:
    document = parse_score(
        f'kind = "motion"\nname = "example"\ntitle = "Example"\n[body]\n{body}\n'
    )
    assert isinstance(document, MotionScore)
    assert isinstance(document.body, expected)
    assert parse_score(score_toml(document)) == document


@pytest.mark.parametrize('kind', ['lfo', 'envelope'])
def test_old_generator_score_kinds_are_rejected(kind: str) -> None:
    with pytest.raises(ValidationError):
        parse_score(f'kind = "{kind}"\nname = "old"\ntitle = "Old"\n')


def test_public_cycle_rate_is_explicitly_bound_and_instantiated() -> None:
    score = MotionScore(
        name='vibrato',
        title='Vibrato',
        parameters={
            'speed': MotionParameter(unit='hz', default=5, minimum=0.1, maximum=20)
        },
        body=Cycle(rate=ParameterReference(parameter='speed')),
    )
    assert parse_score(score_toml(score)) == score
    assert instantiate_motion(score).body == Cycle(rate=Fraction(5))
    assert instantiate_motion(score, {'speed': 6}).body == Cycle(rate=Fraction(6))
    with pytest.raises(ValueError, match='unknown public'):
        instantiate_motion(score, {'depth': 1})
    with pytest.raises(ValueError, match='outside its range'):
        instantiate_motion(score, {'speed': 30})
    with pytest.raises(ValidationError, match='inline cycle rate'):
        MotionUse(body=score.body)


def test_motion_use_requires_exactly_one_definition() -> None:
    with pytest.raises(ValidationError, match='exactly one'):
        MotionUse()
    with pytest.raises(ValidationError, match='exactly one'):
        MotionUse.model_validate(
            {'body': {'kind': 'cycle', 'rate': '1'}, 'score': {'selector': 'vibrato'}}
        )


def test_example_motion_library_resolves_all_scores() -> None:
    library = read_library(Path(__file__).parents[1] / 'examples/motions/library.toml')
    assert not library.diagnostics
    assert {e.name for e in library.find()} == {
        'vibrato',
        'pulse',
        'pluck',
        'bloom',
    }


def test_autonomous_contour_completes_without_note_off() -> None:
    motion = MotionUse(body=Contour(segments=[Segment(duration=Fraction(1), to=1)]))
    state = initial_motion(motion, Fraction(2))
    assert motion_at(motion, state, Fraction(2)).status == 'running'
    assert motion_at(motion, state, Fraction(5, 2)).value == 0.5
    state = motion_event(
        motion,
        state,
        MotionEvent(at=Fraction(5, 2), ordinal=0, action='note_off'),
    )
    assert motion_at(motion, state, Fraction(3)).status == 'complete'
    assert motion_at(motion, state, Fraction(3)).value == 1
    restored = MotionState.model_validate_json(state.model_dump_json())
    assert motion_at(motion, restored, Fraction(3)) == motion_at(
        motion, state, Fraction(3)
    )


def test_triggered_contour_holds_then_releases_from_current_value() -> None:
    motion = MotionUse(
        body=Contour(
            segments=[Segment(duration=Fraction(1), to=1)],
            release=[Segment(duration=Fraction(1), to=0)],
        )
    )
    state = initial_motion(motion, Fraction(0))
    assert motion_at(motion, state, Fraction(0)).status == 'idle'
    state = motion_event(
        motion, state, MotionEvent(at=Fraction(0), ordinal=0, action='note_on')
    )
    assert motion_at(motion, state, Fraction(1)).status == 'held'
    state = motion_event(
        motion, state, MotionEvent(at=Fraction(3, 2), ordinal=0, action='note_off')
    )
    assert motion_at(motion, state, Fraction(2)).value == 0.5
    assert motion_at(motion, state, Fraction(5, 2)).status == 'complete'


def test_cycle_uses_same_value_and_event_contract() -> None:
    motion = MotionUse(body=Cycle(rate=Fraction(1)))
    state = initial_motion(motion, Fraction(0))
    state = motion_event(
        motion,
        state,
        MotionEvent(at=Fraction(1, 4), ordinal=0, action='rate', rate=Fraction(2)),
    )
    assert motion_at(motion, state, Fraction(1, 2)).value == pytest.approx(-1)
    assert motion_at(motion, state, Fraction(1, 2)).status == 'running'
    state = motion_event(
        motion, state, MotionEvent(at=Fraction(1, 2), ordinal=0, action='note_off')
    )
    assert motion_at(motion, state, Fraction(3, 4)).value == pytest.approx(1)
    restored = MotionState.model_validate_json(state.model_dump_json())
    assert motion_at(motion, restored, Fraction(3, 4)) == motion_at(
        motion, state, Fraction(3, 4)
    )


def test_cycle_pause_reverse_and_seek_preserve_seconds_position() -> None:
    motion = MotionUse(body=Cycle(rate=Fraction(1), delay=Fraction(1, 4)))
    state = initial_motion(motion, Fraction(0))
    state = motion_event(
        motion, state, MotionEvent(at=Fraction(1, 4), ordinal=0, action='pause')
    )
    assert motion_at(motion, state, Fraction(2)).value == pytest.approx(1)
    assert motion_at(motion, state, Fraction(2)).weight == 1
    state = motion_event(
        motion, state, MotionEvent(at=Fraction(2), ordinal=0, action='reverse')
    )
    state = motion_event(
        motion, state, MotionEvent(at=Fraction(3), ordinal=0, action='resume')
    )
    assert motion_at(motion, state, Fraction(13, 4)).value == pytest.approx(0)
    state = motion_event(
        motion,
        state,
        MotionEvent(
            at=Fraction(13, 4), ordinal=0, action='seek', position=Fraction(1, 2)
        ),
    )
    assert motion_at(motion, state, Fraction(7, 2)).value == pytest.approx(1)
    restored = MotionState.model_validate_json(state.model_dump_json())
    assert motion_at(motion, restored, Fraction(7, 2)) == motion_at(
        motion, state, Fraction(7, 2)
    )


def test_relative_shift_wraps_cycles_and_clamps_contours() -> None:
    cycle = MotionUse(body=Cycle(rate=Fraction(1)))
    cycle_state = motion_event(
        cycle,
        initial_motion(cycle, Fraction(0)),
        MotionEvent(
            at=Fraction(1, 4),
            ordinal=0,
            action='shift',
            offset=Fraction(-1, 2),
        ),
    )
    assert motion_at(cycle, cycle_state, Fraction(1, 4)).value == pytest.approx(-1)

    contour = MotionUse(body=Contour(segments=[Segment(duration=Fraction(1), to=1)]))
    state = motion_event(
        contour,
        initial_motion(contour, Fraction(0)),
        MotionEvent(
            at=Fraction(1, 2),
            ordinal=0,
            action='shift',
            offset=Fraction(3, 4),
        ),
    )
    assert motion_at(contour, state, Fraction(1, 2)).value == 1
    state = motion_event(
        contour,
        state,
        MotionEvent(
            at=Fraction(1, 2),
            ordinal=1,
            action='shift',
            offset=Fraction(-1, 2),
        ),
    )
    assert motion_at(contour, state, Fraction(1, 2)).value == pytest.approx(0.5)


@pytest.mark.parametrize(
    ('mode', 'at_end', 'after_end'),
    [
        (PlaybackMode.loop, 0, 0.25),
        (PlaybackMode.ping_pong, 1, 0.75),
    ],
)
def test_contour_playback_loops_and_releases_from_current_value(
    mode: PlaybackMode, at_end: float, after_end: float
) -> None:
    motion = MotionUse(
        body=Contour(
            segments=[Segment(duration=Fraction(1), to=1)],
            release=[Segment(duration=Fraction(1), to=0)],
            playback=mode,
        )
    )
    state = motion_event(
        motion,
        initial_motion(motion, Fraction(0)),
        MotionEvent(at=Fraction(0), ordinal=0, action='note_on'),
    )
    assert motion_at(motion, state, Fraction(1)).value == at_end
    assert motion_at(motion, state, Fraction(5, 4)).value == after_end
    assert motion_at(motion, state, Fraction(5, 4)).status == 'running'
    state = motion_event(
        motion,
        state,
        MotionEvent(at=Fraction(5, 4), ordinal=0, action='note_off'),
    )
    assert motion_at(motion, state, Fraction(5, 4)).value == after_end
    assert motion_at(motion, state, Fraction(7, 4)).value == pytest.approx(
        after_end / 2
    )
    assert motion_at(motion, state, Fraction(9, 4)).status == 'complete'
    restored = MotionState.model_validate_json(state.model_dump_json())
    assert motion_at(motion, restored, Fraction(7, 4)) == motion_at(
        motion, state, Fraction(7, 4)
    )
    with pytest.raises(ValueError, match='cannot be converted'):
        contour_envelope(motion)


def test_looping_contour_shift_keeps_unwrapped_position() -> None:
    motion = MotionUse(
        body=Contour(
            segments=[Segment(duration=Fraction(1), to=1)],
            playback=PlaybackMode.ping_pong,
        )
    )
    state = motion_event(
        motion,
        initial_motion(motion, Fraction(0)),
        MotionEvent(
            at=Fraction(1, 4),
            ordinal=0,
            action='shift',
            offset=Fraction(3, 2),
        ),
    )
    assert motion_at(motion, state, Fraction(1, 4)).value == 0.25
    assert motion_at(motion, state, Fraction(1, 2)).value == 0


@pytest.mark.parametrize(
    ('mode', 'ports'),
    [
        (
            PlaybackMode.loop,
            [
                (Fraction(1, 4), 'quarter'),
                (Fraction(1), 'cycle'),
                (Fraction(5, 4), 'quarter'),
                (Fraction(2), 'cycle'),
                (Fraction(9, 4), 'quarter'),
            ],
        ),
        (
            PlaybackMode.ping_pong,
            [
                (Fraction(1, 4), 'quarter'),
                (Fraction(1), 'turned'),
                (Fraction(7, 4), 'quarter'),
                (Fraction(2), 'turned'),
                (Fraction(2), 'cycle'),
                (Fraction(9, 4), 'quarter'),
            ],
        ),
    ],
)
def test_staged_contour_playback_orders_markers_and_boundaries(
    mode: PlaybackMode, ports: list[tuple[Fraction, str]]
) -> None:
    motion = MotionUse(
        body=Stages(
            initial_stage='sweep',
            stages=[
                Stage(
                    name='sweep',
                    motion=Contour(
                        segments=[Segment(duration=Fraction(1), to=1)],
                        playback=mode,
                        markers=[Marker(name='quarter', position=Fraction(1, 4))],
                    ),
                )
            ],
        )
    )
    result = advance_motion(motion, initial_motion(motion, Fraction(0)), Fraction(9, 4))
    assert [(e.at, e.port) for e in result.events] == ports
    assert result.value.value == 0.25
    assert result.value.status == 'running'
    assert advance_motion(motion, result.state, Fraction(5, 2)).events == []


@pytest.mark.parametrize(
    ('mode', 'captured'),
    [(PlaybackMode.loop, 0.25), (PlaybackMode.ping_pong, 0.75)],
)
def test_staged_loop_releases_immediately_from_current_value(
    mode: PlaybackMode, captured: float
) -> None:
    motion = MotionUse(
        body=Stages(
            initial_stage='sweep',
            stages=[
                Stage(
                    name='sweep',
                    motion=Contour(
                        segments=[Segment(duration=Fraction(1), to=1)],
                        playback=mode,
                    ),
                ),
                Stage(
                    name='release',
                    motion=Contour(
                        initial='current',
                        segments=[Segment(duration=Fraction(1), to=0)],
                    ),
                ),
            ],
            transitions=[
                StageTransition(
                    **{
                        'from': ['sweep'],
                        'event': 'note_off',
                        'action': EnterStage(stage='release'),
                    }
                )
            ],
        )
    )
    release = MotionEvent(at=Fraction(5, 4), ordinal=0, action='note_off')
    result = advance_motion(
        motion, initial_motion(motion, Fraction(0)), release.at, release
    )
    assert result.state.runtime.stage == 'release'
    assert result.value.value == captured
    assert advance_motion(
        motion, result.state, Fraction(7, 4)
    ).value.value == pytest.approx(captured / 2)


def test_staged_loop_cycle_port_can_enter_another_stage() -> None:
    motion = MotionUse(
        body=Stages(
            initial_stage='sweep',
            stages=[
                Stage(
                    name='sweep',
                    motion=Contour(
                        segments=[Segment(duration=Fraction(1), to=1)],
                        playback=PlaybackMode.loop,
                    ),
                ),
                Stage(name='held', motion=Hold(value=0.75)),
            ],
            transitions=[
                StageTransition(
                    **{
                        'from': ['sweep'],
                        'event': 'stage.cycle',
                        'action': EnterStage(stage='held'),
                    }
                )
            ],
        )
    )
    result = advance_motion(motion, initial_motion(motion, Fraction(0)), Fraction(2))
    assert [(e.at, e.port) for e in result.events] == [(Fraction(1), 'cycle')]
    assert result.state.runtime.stage == 'held'
    assert result.value.value == 0.75


@pytest.mark.parametrize(
    'motion',
    [
        Contour(
            segments=[Segment(duration=Fraction(1), to=1)],
            markers=[Marker(name='done', position=Fraction(1, 2))],
        ),
        Cycle(
            rate=Fraction(1),
            markers=[Marker(name='done', position=Fraction(1, 2))],
        ),
    ],
)
def test_staged_marker_cannot_claim_completion_port(motion: Contour | Cycle) -> None:
    with pytest.raises(ValidationError, match='reserved for completion'):
        Stages(
            initial_stage='moving',
            stages=[Stage(name='moving', motion=motion)],
        )


@pytest.mark.parametrize(
    ('mode', 'boundary_events', 'value'),
    [
        (
            PlaybackMode.loop,
            [
                (Fraction(1, 4), 'start'),
                (Fraction(3, 4), 'start'),
                (Fraction(3, 4), 'end'),
                (Fraction(3, 4), 'cycle'),
                (Fraction(5, 4), 'start'),
                (Fraction(5, 4), 'end'),
                (Fraction(5, 4), 'cycle'),
            ],
            0.25,
        ),
        (
            PlaybackMode.ping_pong,
            [
                (Fraction(1, 4), 'start'),
                (Fraction(3, 4), 'end'),
                (Fraction(3, 4), 'turned'),
                (Fraction(5, 4), 'start'),
                (Fraction(5, 4), 'turned'),
                (Fraction(5, 4), 'cycle'),
            ],
            0.25,
        ),
    ],
)
def test_named_contour_loop_boundaries_preserve_markers_and_events(
    mode: PlaybackMode,
    boundary_events: list[tuple[Fraction, str]],
    value: float,
) -> None:
    contour = Contour(
        segments=[Segment(duration=Fraction(1), to=1)],
        playback=mode,
        markers=[
            Marker(name='start', position=Fraction(1, 4)),
            Marker(name='end', position=Fraction(3, 4)),
        ],
        loop_start='start',
        loop_end='end',
    )
    motion = MotionUse(
        body=Stages(
            initial_stage='sweep',
            stages=[Stage(name='sweep', motion=contour)],
        )
    )
    result = advance_motion(motion, initial_motion(motion, Fraction(0)), Fraction(5, 4))
    assert [(e.at, e.port) for e in result.events] == boundary_events
    assert result.value.value == value
    standalone = MotionUse(body=contour)
    started = motion_event(
        standalone,
        initial_motion(standalone, Fraction(0)),
        MotionEvent(at=Fraction(0), ordinal=0, action='note_on'),
    )
    assert motion_at(standalone, started, Fraction(1)).value == 0.5


def test_named_loop_reverse_orders_boundary_markers_before_cycle() -> None:
    motion = MotionUse(
        body=Stages(
            initial_stage='sweep',
            stages=[
                Stage(
                    name='sweep',
                    motion=Contour(
                        segments=[Segment(duration=Fraction(1), to=1)],
                        playback=PlaybackMode.loop,
                        markers=[
                            Marker(name='start', position=Fraction(1, 4)),
                            Marker(name='end', position=Fraction(3, 4)),
                        ],
                        loop_start='start',
                        loop_end='end',
                    ),
                )
            ],
        )
    )
    forward = advance_motion(motion, initial_motion(motion, Fraction(0)), Fraction(1))
    reversed_state = advance_motion(
        motion,
        forward.state,
        Fraction(1),
        MotionEvent(at=Fraction(1), ordinal=0, action='reverse'),
    ).state
    result = advance_motion(motion, reversed_state, Fraction(5, 4))
    assert [(e.at, e.port) for e in result.events] == [
        (Fraction(5, 4), 'end'),
        (Fraction(5, 4), 'start'),
        (Fraction(5, 4), 'cycle'),
    ]
    assert (
        MotionState.model_validate_json(result.state.model_dump_json()) == result.state
    )


@pytest.mark.parametrize(
    ('mode', 'events', 'value'),
    [
        (PlaybackMode.loop, ['cycle', 'cycle', 'stage.done'], 1.0),
        (
            PlaybackMode.ping_pong,
            ['turned', 'turned', 'cycle', 'stage.done'],
            0.0,
        ),
    ],
)
def test_finite_contour_repeats_hold_final_boundary(
    mode: PlaybackMode, events: list[str], value: float
) -> None:
    contour = Contour(
        segments=[Segment(duration=Fraction(1), to=1)],
        playback=mode,
        repeat_count=2,
    )
    staged = MotionUse(
        body=Stages(
            initial_stage='sweep',
            stages=[Stage(name='sweep', motion=contour)],
        )
    )
    result = advance_motion(staged, initial_motion(staged, Fraction(0)), Fraction(3))
    assert [e.port for e in result.events] == events
    assert result.value.value == value
    assert result.value.status == 'complete'
    assert advance_motion(staged, result.state, Fraction(4)).events == []
    assert (
        MotionState.model_validate_json(result.state.model_dump_json()) == result.state
    )

    standalone = MotionUse(body=contour)
    initial = initial_motion(standalone, Fraction(0))
    assert motion_at(standalone, initial, Fraction(3)).value == value
    assert motion_at(standalone, initial, Fraction(3)).status == 'complete'
    state = motion_event(
        standalone,
        initial,
        MotionEvent(at=Fraction(3), ordinal=0, action='pause'),
    )
    assert motion_at(standalone, state, Fraction(4)).value == value


def test_finite_named_loop_counts_reverse_boundary_crossing() -> None:
    contour = Contour(
        segments=[Segment(duration=Fraction(1), to=1)],
        playback=PlaybackMode.loop,
        markers=[
            Marker(name='start', position=Fraction(1, 4)),
            Marker(name='end', position=Fraction(3, 4)),
        ],
        loop_start='start',
        loop_end='end',
        repeat_count=2,
    )
    staged = MotionUse(
        body=Stages(
            initial_stage='sweep',
            stages=[Stage(name='sweep', motion=contour)],
        )
    )
    forward = advance_motion(staged, initial_motion(staged, Fraction(0)), Fraction(1))
    reversed_state = advance_motion(
        staged,
        forward.state,
        Fraction(1),
        MotionEvent(at=Fraction(1), ordinal=0, action='reverse'),
    ).state
    final = advance_motion(staged, reversed_state, Fraction(2))
    assert [(e.at, e.port) for e in final.events] == [
        (Fraction(5, 4), 'end'),
        (Fraction(5, 4), 'start'),
        (Fraction(5, 4), 'cycle'),
        (Fraction(5, 4), 'stage.done'),
    ]
    assert final.value.value == 0.25
    assert final.value.status == 'complete'


def test_final_repeat_emits_done_before_entering_next_stage() -> None:
    motion = MotionUse(
        body=Stages(
            initial_stage='sweep',
            stages=[
                Stage(
                    name='sweep',
                    motion=Contour(
                        segments=[Segment(duration=Fraction(1), to=1)],
                        playback=PlaybackMode.loop,
                        repeat_count=1,
                    ),
                ),
                Stage(name='held', motion=Hold(value=0.5)),
            ],
            transitions=[
                StageTransition(
                    **{
                        'from': ['sweep'],
                        'event': 'stage.cycle',
                        'action': EnterStage(stage='held'),
                    }
                )
            ],
        )
    )
    result = advance_motion(motion, initial_motion(motion, Fraction(0)), Fraction(2))
    assert [e.port for e in result.events] == ['cycle', 'stage.done']
    assert result.state.runtime.stage == 'held'
    assert result.value.value == 0.5


def test_repeat_count_requires_repeating_contour() -> None:
    with pytest.raises(ValidationError, match='requires loop'):
        Contour(segments=[Segment(duration=Fraction(1), to=1)], repeat_count=1)


def test_contour_reverses_through_segments_without_recapturing_start() -> None:
    motion = MotionUse(
        body=Contour(
            segments=[Segment(duration=Fraction(1), to=1)],
            release=[Segment(duration=Fraction(1), to=0)],
        )
    )
    state = motion_event(
        motion,
        initial_motion(motion, Fraction(0)),
        MotionEvent(at=Fraction(0), ordinal=0, action='note_on'),
    )
    state = motion_event(
        motion, state, MotionEvent(at=Fraction(3, 4), ordinal=0, action='reverse')
    )
    assert motion_at(motion, state, Fraction(1)).value == pytest.approx(0.5)
    state = motion_event(
        motion, state, MotionEvent(at=Fraction(1), ordinal=0, action='pause')
    )
    assert motion_at(motion, state, Fraction(3)).value == pytest.approx(0.5)
    state = motion_event(
        motion,
        state,
        MotionEvent(at=Fraction(3), ordinal=0, action='seek', position=Fraction(1)),
    )
    assert motion_at(motion, state, Fraction(3)).status == 'held'
    state = motion_event(
        motion, state, MotionEvent(at=Fraction(3), ordinal=1, action='note_off')
    )
    assert motion_at(motion, state, Fraction(3)).value == 1


def test_staged_reverse_markers_and_seek_do_not_undo_transitions() -> None:
    motion = staged_motion()
    cue = MotionEvent(at=Fraction(0), ordinal=0, action='cue', cue='sway')
    state = advance_motion(motion, initial_motion(motion, cue.at), cue.at, cue).state
    first = advance_motion(motion, state, Fraction(3, 8))
    assert [(e.at, e.port) for e in first.events] == [(Fraction(1, 8), 'peak')]
    reversed_at = MotionEvent(at=Fraction(3, 8), ordinal=0, action='reverse')
    state = advance_motion(motion, first.state, reversed_at.at, reversed_at).state
    backward = advance_motion(motion, state, Fraction(5, 8))
    assert [(e.at, e.port) for e in backward.events] == [(Fraction(5, 8), 'peak')]
    seek = MotionEvent(
        at=Fraction(5, 8), ordinal=0, action='seek', position=Fraction(3, 4)
    )
    jumped = advance_motion(motion, backward.state, seek.at, seek)
    assert jumped.events == []
    assert jumped.state.runtime.stage == 'sway'
    assert advance_motion(motion, jumped.state, Fraction(7, 8)).events == [
        backward.events[0].model_copy(update={'at': Fraction(7, 8)})
    ]


def test_unconnected_stage_completion_emits_once() -> None:
    motion = MotionUse(
        body=Stages(
            initial_stage='rise',
            stages=[
                Stage(
                    name='rise',
                    motion=Contour(segments=[Segment(duration=Fraction(1, 4), to=1)]),
                )
            ],
        )
    )
    first = advance_motion(motion, initial_motion(motion, Fraction(0)), Fraction(1, 4))
    assert [e.port for e in first.events] == ['stage.done']
    assert advance_motion(motion, first.state, Fraction(1)).events == []


def test_stages_attack_sways_releases_and_emits_completion() -> None:
    motion = staged_motion()
    assert MotionUse.model_validate_json(motion.model_dump_json()) == motion
    score = MotionScore(name='bloom', title='Bloom', body=motion.body)
    assert parse_score(score_toml(score)) == score
    state = initial_motion(motion, Fraction(0))
    assert motion_at(motion, state, Fraction(0)).value == 0
    start = advance_motion(
        motion,
        state,
        Fraction(0),
        MotionEvent(at=Fraction(0), ordinal=0, action='note_on'),
    )
    attack_end = advance_motion(motion, start.state, Fraction(1, 4))
    assert attack_end.value.value == pytest.approx(0.7)
    assert [(e.at, e.port, e.stage) for e in attack_end.events] == [
        (Fraction(1, 4), 'stage.done', 'attack')
    ]
    peak = advance_motion(motion, attack_end.state, Fraction(3, 8))
    assert peak.value.value == pytest.approx(0.9)
    assert [(e.at, e.port, e.stage) for e in peak.events] == [
        (Fraction(3, 8), 'peak', 'sway')
    ]
    release = advance_motion(
        motion,
        peak.state,
        Fraction(3, 8),
        MotionEvent(at=Fraction(3, 8), ordinal=0, action='note_off'),
    )
    assert release.value.value == pytest.approx(0.9)
    restored = MotionState.model_validate_json(release.state.model_dump_json())
    done = advance_motion(motion, restored, Fraction(5, 8))
    assert done.value.status == 'complete'
    assert done.value.value == pytest.approx(0)
    assert [(e.port, e.stage) for e in done.events] == [
        ('stage.done', 'release'),
        ('done', 'release'),
    ]
    assert advance_motion(motion, done.state, Fraction(1)).events == []


def test_note_off_at_stage_end_discards_obsolete_completion() -> None:
    motion = staged_motion()
    start = advance_motion(
        motion,
        initial_motion(motion, Fraction(0)),
        Fraction(0),
        MotionEvent(at=Fraction(0), ordinal=0, action='note_on'),
    )
    release = advance_motion(
        motion,
        start.state,
        Fraction(1, 4),
        MotionEvent(at=Fraction(1, 4), ordinal=0, action='note_off'),
    )
    assert release.events == []
    assert release.value.value == pytest.approx(0.7)
    assert release.state.runtime.stage == 'release'
    done = advance_motion(motion, release.state, Fraction(1, 2))
    assert [e.port for e in done.events] == ['stage.done', 'done']


def test_stage_cue_and_marker_crossings_are_partition_independent() -> None:
    motion = staged_motion()
    cue = MotionEvent(at=Fraction(0), ordinal=0, action='cue', cue='sway')
    start = advance_motion(motion, initial_motion(motion, Fraction(0)), cue.at, cue)
    whole = advance_motion(motion, start.state, Fraction(1))
    pieces = []
    state = start.state
    for end in (Fraction(1, 8), Fraction(1, 4), Fraction(3, 4), Fraction(1)):
        result = advance_motion(motion, state, end)
        pieces.extend(result.events)
        state = result.state
    assert [(e.at, e.port) for e in whole.events] == [
        (Fraction(1, 8), 'peak'),
        (Fraction(5, 8), 'peak'),
    ]
    assert pieces == whole.events
    assert motion_at(motion, state, Fraction(1)) == whole.value
