from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor.codec import parse_score, score_toml
from ufor.envelfo import (
    LFO,
    Contour,
    EnterStage,
    EnvelfoParameter,
    EnvelfoScore,
    EnvelfoUse,
    FinishStage,
    Hold,
    Marker,
    ParameterReference,
    Patch,
    SampleHold,
    Stage,
    Stages,
    StageTransition,
    Sum,
    instantiate_envelfo,
)
from ufor.library_files import read_library
from ufor.samples.processing import ReleaseTiming, SoundSettings
from ufor.segments import Segment


def staged_envelfo() -> EnvelfoUse:
    return EnvelfoUse(
        body=Stages(
            initial_stage='waiting',
            stages=[
                Stage(name='waiting', envelfo=Hold(value=0.0)),
                Stage(
                    name='attack',
                    envelfo=Contour(
                        initial='current',
                        segments=[Segment(duration=Fraction(1, 4), to=0.7)],
                    ),
                ),
                Stage(
                    name='sway',
                    envelfo=LFO(
                        rate=Fraction(2),
                        center=0.7,
                        depth=0.2,
                        markers=[Marker(name='peak', position=Fraction(1, 4))],
                    ),
                ),
                Stage(
                    name='release',
                    envelfo=Contour(
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


def test_envelfo_score_rejects_previous_kind() -> None:
    score = EnvelfoScore(name='pulse', title='Pulse', body=LFO(rate=1))
    text = score_toml(score)
    assert parse_score(text) == score
    with pytest.raises(ValidationError, match='union_tag_invalid'):
        parse_score(text.replace('kind = "envelfo"', 'kind = "motion"', 1))


def test_envelfo_fields_reject_previous_spelling() -> None:
    with pytest.raises(ValidationError, match='Extra inputs are not permitted'):
        Stage.model_validate({'name': 'held', 'motion': {'kind': 'hold', 'value': 0}})
    with pytest.raises(ValidationError, match='Extra inputs are not permitted'):
        SoundSettings.model_validate({'motions': {}})


def test_lfo_rejects_previous_body_kind() -> None:
    definition = EnvelfoUse(body=LFO(rate=1))
    assert definition.model_dump()['body']['kind'] == 'lfo'
    with pytest.raises(ValidationError, match='union_tag_invalid'):
        EnvelfoUse.model_validate({'body': {'kind': 'cycle', 'rate': 1}})


def test_stage_contour_durations_match_the_envelfo_clock() -> None:
    body = {
        'kind': 'stages',
        'initial_stage': 'attack',
        'stages': [
            {
                'name': 'attack',
                'envelfo': {
                    'kind': 'contour',
                    'segments': [{'duration': '1 beat', 'to': 1}],
                },
            }
        ],
    }
    envelfo = EnvelfoUse.model_validate({'clock': 'beats', 'body': body})
    assert envelfo.clock.value == 'beats'
    with pytest.raises(ValidationError, match='stage contour segment units'):
        EnvelfoUse.model_validate({'clock': 'seconds', 'body': body})


def test_voice_envelfo_event_connections_validate_ports_and_cues() -> None:
    source = staged_envelfo()
    destination = EnvelfoUse(
        body=Stages(
            initial_stage='waiting',
            stages=[
                Stage(name='waiting', envelfo=Hold(value=0.0)),
                Stage(name='bright', envelfo=Hold(value=1.0)),
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
        'envelfos': {
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
            {'name': 'source', 'kind': 'envelfo', 'reference': 'source'},
            {'name': 'destination', 'kind': 'envelfo', 'reference': 'destination'},
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
    raw['envelfos']['source']['body']['stages'][2]['envelfo'] = {
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
    raw['envelfos']['source']['body']['stages'][2]['envelfo']['playback'] = 'ping_pong'
    assert SoundSettings.model_validate(raw).event_connections[0].port == 'turned'


def test_named_contour_release_timing_is_explicit_and_contour_only() -> None:
    raw = {
        'envelfos': {
            'envelfo': {
                'body': {
                    'kind': 'contour',
                    'segments': [{'duration': '1 s', 'to': 1}],
                    'release': [{'duration': '1 s', 'to': 0}],
                }
            }
        },
        'modulation': {
            'sources': [
                {'name': 'envelfo', 'scope': 'voice', 'minimum': 0, 'maximum': 1}
            ]
        },
        'bindings': [{'name': 'envelfo', 'kind': 'envelfo', 'reference': 'envelfo'}],
    }
    default = SoundSettings.model_validate(raw)
    assert default.bindings[0].release_timing == ReleaseTiming.event
    raw['bindings'][0]['release_timing'] = 'voice'
    selected = SoundSettings.model_validate(raw)
    assert selected.bindings[0].release_timing == ReleaseTiming.voice
    assert SoundSettings.model_validate_json(selected.model_dump_json()) == selected
    raw['envelfos']['envelfo']['body']['release'] = []
    with pytest.raises(ValidationError, match='releasing contour'):
        SoundSettings.model_validate(raw)
    raw['envelfos']['envelfo']['body'] = {'kind': 'lfo', 'rate': '1'}
    raw['modulation']['sources'][0]['minimum'] = -1
    with pytest.raises(ValidationError, match='releasing contour'):
        SoundSettings.model_validate(raw)


def test_patch_sample_commands_select_only_sample_hold_children() -> None:
    patch = Patch.model_validate(
        {
            'envelfos': {
                'clock': {
                    'kind': 'lfo',
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
    score = EnvelfoScore(name='random', title='Random', body=patch)
    assert parse_score(score_toml(score)) == score
    raw = patch.model_dump(mode='json')
    raw['events'][0]['target'] = 'clock'
    with pytest.raises(ValidationError, match='sample target'):
        Patch.model_validate(raw)
    with pytest.raises(ValidationError, match='voice scope'):
        EnvelfoUse(body=patch, scope='instrument')
    with pytest.raises(ValidationError, match='minimum'):
        SampleHold(minimum=0.5, maximum=0.25)


@pytest.mark.parametrize(
    ('inputs', 'message'),
    [(['missing', 'carrier'], 'unknown child'), (['output', 'carrier'], 'lfo')],
)
def test_patch_transform_dependencies_are_validated(
    inputs: list[str], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Patch(
            envelfos={'carrier': LFO(rate=1), 'output': Sum(inputs=inputs)},
            outputs={'signal': 'output'},
        )


def test_patch_transformed_output_requires_a_covering_source_domain() -> None:
    raw = {
        'envelfos': {
            'patch': {
                'body': {
                    'kind': 'patch',
                    'envelfos': {
                        'lfo': {'kind': 'lfo', 'rate': '1'},
                        'sum': {'kind': 'sum', 'inputs': ['lfo', 'lfo']},
                    },
                    'outputs': {'signal': 'sum'},
                }
            }
        },
        'bindings': [
            {
                'name': 'signal',
                'kind': 'envelfo',
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
        'envelfos': {
            'gesture': {
                'body': {
                    'kind': 'patch',
                    'envelfos': {
                        'amp': {
                            'kind': 'contour',
                            'segments': [{'duration': '1 s', 'to': 1}],
                        },
                        'vibrato': {'kind': 'lfo', 'rate': '5'},
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
                'kind': 'envelfo',
                'reference': 'gesture',
                'output': 'level',
            },
            {
                'name': 'pitch',
                'kind': 'envelfo',
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
    raw['envelfos']['gesture']['body']['outputs']['pitch'] = 'amp'
    raw['envelfos']['gesture']['body']['envelfos']['amp']['release'] = [
        {'duration': '1 s', 'to': 0}
    ]
    assert SoundSettings.model_validate(raw)
    raw['bindings'][1]['release_timing'] = 'voice'
    with pytest.raises(ValidationError, match='one release timing'):
        SoundSettings.model_validate(raw)


def test_patch_output_and_clock_references_are_validated() -> None:
    body = {
        'kind': 'patch',
        'envelfos': {
            'amp': {
                'kind': 'contour',
                'segments': [{'duration': '1 beat', 'to': 1}],
            }
        },
        'outputs': {'level': 'amp'},
    }
    score = EnvelfoScore.model_validate(
        {'name': 'gesture', 'title': 'Gesture', 'body': body}
    )
    assert parse_score(score_toml(score)) == score
    assert isinstance(EnvelfoUse(clock='beats', body=score.body).body, type(score.body))
    with pytest.raises(ValidationError, match='patch contour segment units'):
        EnvelfoUse(body=score.body)
    body['outputs']['level'] = 'missing'
    with pytest.raises(ValidationError, match='unknown child Envelfo'):
        EnvelfoScore.model_validate(
            {'name': 'gesture', 'title': 'Gesture', 'body': body}
        )


def test_patch_marker_cues_child_stages() -> None:
    body = {
        'kind': 'patch',
        'envelfos': {
            'clock': {
                'kind': 'lfo',
                'rate': '2',
                'markers': [{'name': 'peak', 'position': '1/4'}],
            },
            'level': {
                'kind': 'stages',
                'initial_stage': 'waiting',
                'stages': [
                    {'name': 'waiting', 'envelfo': {'kind': 'hold'}},
                    {'name': 'bright', 'envelfo': {'kind': 'hold', 'value': 1}},
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
    score = EnvelfoScore.model_validate(
        {'name': 'gesture', 'title': 'Gesture', 'body': body}
    )
    assert parse_score(score_toml(score)) == score
    body['events'][0]['cue'] = 'missing'
    with pytest.raises(ValidationError, match='matching stage transition'):
        EnvelfoUse.model_validate({'body': body})
    body['events'][0].pop('cue')
    with pytest.raises(ValidationError, match='require a cue name'):
        EnvelfoUse.model_validate({'body': body})


@pytest.mark.parametrize('source_kind', ['marker', 'stage.done'])
def test_patch_stage_event_commands_children(source_kind: str) -> None:
    port = 'peak' if source_kind == 'marker' else 'stage.done'
    clock = {
        'kind': 'stages',
        'initial_stage': 'playing',
        'stages': [
            {
                'name': 'playing',
                'envelfo': {
                    'kind': 'lfo',
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
        'envelfos': {
            'clock': clock,
            'level': {
                'kind': 'stages',
                'initial_stage': 'waiting',
                'stages': [
                    {'name': 'waiting', 'envelfo': {'kind': 'hold'}},
                    {'name': 'bright', 'envelfo': {'kind': 'hold', 'value': 1}},
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
    score = EnvelfoScore.model_validate(
        {'name': 'gesture', 'title': 'Gesture', 'body': body}
    )
    assert parse_score(score_toml(score)) == score
    with pytest.raises(ValidationError, match='voice scope'):
        EnvelfoUse.model_validate({'body': body, 'scope': 'part'})
    body['events'][0]['source'] = 'clock.missing'
    with pytest.raises(ValidationError, match='unknown stage event'):
        EnvelfoUse.model_validate({'body': body})
    body['envelfos']['accent'] = {
        'kind': 'contour',
        'start': 'event',
        'segments': [{'duration': '1/4 s', 'to': 1}],
    }
    body['outputs'] = {'value': 'accent'}
    body['events'][0]['source'] = f'clock.{port}'
    body['events'][0]['target'] = 'accent'
    body['events'][0]['action'] = 'start'
    body['events'][0].pop('cue')
    score = EnvelfoScore.model_validate(
        {'name': 'gesture', 'title': 'Gesture', 'body': body}
    )
    assert parse_score(score_toml(score)) == score
    body['envelfos']['accent']['start'] = 'activation'
    with pytest.raises(ValidationError, match='event-start Contour'):
        EnvelfoUse.model_validate({'body': body})


@pytest.mark.parametrize('child_kind', ['lfo', 'stages'])
def test_patch_named_event_output_validates_child_port(child_kind: str) -> None:
    child = {
        'kind': 'lfo',
        'rate': '1',
        'markers': [{'name': 'peak', 'position': '1/4'}],
    }
    if child_kind == 'stages':
        child = {
            'kind': 'stages',
            'initial_stage': 'playing',
            'stages': [{'name': 'playing', 'envelfo': child}],
        }
    body = {
        'kind': 'patch',
        'envelfos': {'pulse': child},
        'outputs': {'signal': 'pulse'},
        'event_outputs': {'strike': 'pulse.peak'},
    }
    patch = EnvelfoUse.model_validate({'body': body})
    assert EnvelfoUse.model_validate_json(patch.model_dump_json()) == patch
    settings = {
        'envelfos': {
            'patch': {'body': body},
            'level': {
                'body': {
                    'kind': 'stages',
                    'initial_stage': 'waiting',
                    'stages': [
                        {'name': 'waiting', 'envelfo': {'kind': 'hold'}},
                        {'name': 'bright', 'envelfo': {'kind': 'hold', 'value': 1}},
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
                'kind': 'envelfo',
                'reference': 'patch',
                'output': 'signal',
            },
            {'name': 'level', 'kind': 'envelfo', 'reference': 'level'},
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
        assert EnvelfoUse.model_validate({'body': body})
    body['event_outputs']['strike'] = 'pulse.missing'
    with pytest.raises(ValidationError, match='unknown child event'):
        EnvelfoUse.model_validate({'body': body})


@pytest.mark.parametrize(
    ('body', 'expected'),
    [
        ('kind = "lfo"\nshape = "sine"\nrate = "5 Hz"', LFO),
        (
            'kind = "contour"\ninitial = 0.0\n'
            'segments = [{ duration = "10 ms", to = 1.0 }]\n'
            'release = [{ duration = "200 ms", to = 0.0 }]',
            Contour,
        ),
    ],
)
def test_envelfo_score_round_trips_simple_bodies(
    body: str, expected: type[object]
) -> None:
    document = parse_score(
        f'kind = "envelfo"\nname = "example"\ntitle = "Example"\n[body]\n{body}\n'
    )
    assert isinstance(document, EnvelfoScore)
    assert isinstance(document.body, expected)
    assert parse_score(score_toml(document)) == document


@pytest.mark.parametrize('kind', ['lfo', 'envelope'])
def test_old_generator_score_kinds_are_rejected(kind: str) -> None:
    with pytest.raises(ValidationError):
        parse_score(f'kind = "{kind}"\nname = "old"\ntitle = "Old"\n')


def test_public_lfo_rate_is_explicitly_bound_and_instantiated() -> None:
    score = EnvelfoScore(
        name='vibrato',
        title='Vibrato',
        parameters={
            'speed': EnvelfoParameter(unit='hz', default=5, minimum=0.1, maximum=20)
        },
        body=LFO(rate=ParameterReference(parameter='speed')),
    )
    assert parse_score(score_toml(score)) == score
    assert instantiate_envelfo(score).body == LFO(rate=Fraction(5))
    assert instantiate_envelfo(score, {'speed': 6}).body == LFO(rate=Fraction(6))
    with pytest.raises(ValueError, match='unknown public'):
        instantiate_envelfo(score, {'depth': 1})
    with pytest.raises(ValueError, match='outside its range'):
        instantiate_envelfo(score, {'speed': 30})
    with pytest.raises(ValidationError, match='inline LFO rate'):
        EnvelfoUse(body=score.body)


def test_envelfo_use_requires_exactly_one_definition() -> None:
    with pytest.raises(ValidationError, match='exactly one'):
        EnvelfoUse()
    with pytest.raises(ValidationError, match='exactly one'):
        EnvelfoUse.model_validate(
            {'body': {'kind': 'lfo', 'rate': '1'}, 'score': {'selector': 'vibrato'}}
        )


def test_example_envelfo_library_resolves_all_scores() -> None:
    library = read_library(Path(__file__).parents[1] / 'examples/envelfos/library.toml')
    assert not library.diagnostics
    assert {e.name for e in library.find()} == {
        'vibrato',
        'pulse',
        'pluck',
        'bloom',
    }


@pytest.mark.parametrize(
    'envelfo',
    [
        Contour(
            segments=[Segment(duration=Fraction(1), to=1)],
            markers=[Marker(name='done', position=Fraction(1, 2))],
        ),
        LFO(
            rate=Fraction(1),
            markers=[Marker(name='done', position=Fraction(1, 2))],
        ),
    ],
)
def test_staged_marker_cannot_claim_completion_port(envelfo: Contour | LFO) -> None:
    with pytest.raises(ValidationError, match='reserved for completion'):
        Stages(
            initial_stage='moving',
            stages=[Stage(name='moving', envelfo=envelfo)],
        )


def test_repeat_count_requires_repeating_contour() -> None:
    with pytest.raises(ValidationError, match='requires loop'):
        Contour(segments=[Segment(duration=Fraction(1), to=1)], repeat_count=1)
