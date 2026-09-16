import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from ufor import modulation, synth, synth_trace
from ufor.events import ControlChange, PerformanceEvent, Release, Trigger
from ufor.instrument_trace import TriggerContext, VoiceRetirement
from ufor.samples import trace
from ufor.samples.instrument import SampleInstrument
from ufor.synth import SynthInstrument

CASES = json.loads(
    (Path(__file__).parents[1] / 'conformance/instrument-lifecycle.json').read_text()
)


@pytest.mark.parametrize('kind', ['sample', 'synth'])
@pytest.mark.parametrize('case', CASES['cases'], ids=lambda c: c['name'])
def test_shared_lifecycle_conformance(kind: str, case: dict[str, object]) -> None:
    events = TypeAdapter(list[PerformanceEvent]).validate_python(case['events'])
    result = prepare(kind, case['templates'], events, case['settings'])
    actions = [
        {
            k: v
            for k, v in a.model_dump(mode='json', exclude_none=True).items()
            if k in CASES['action_fields']
        }
        for a in result.actions
    ]
    assert actions == case['actions']
    assert [v.voice_id for v in result.snapshots[-1].voices] == case['active_voice_ids']


@pytest.mark.parametrize('kind', ['sample', 'synth'])
@pytest.mark.parametrize(
    'mode,action', [('immediate', 'stop'), ('release', 'release'), ('fade', 'fade')]
)
def test_chokes_preserve_mode_and_part(kind: str, mode: str, action: str) -> None:
    choke = {'group': 'held', 'mode': mode}
    if mode == 'fade':
        choke['fade_seconds'] = 0.25
    result = prepare(
        kind,
        [
            {
                'name': 'held',
                'choke_group': 'held',
                'mapping': {
                    'lowest_key': 60,
                    'highest_key': 60,
                    'pitch_tracking': False,
                },
            },
            {
                'name': 'choker',
                'chokes': [choke],
                'mapping': {
                    'lowest_key': 61,
                    'highest_key': 61,
                    'pitch_tracking': False,
                },
            },
        ],
        [
            Trigger(tick=0, ordinal=0, part='left', trigger_id='one', key=60),
            Trigger(tick=1, ordinal=1, part='right', trigger_id='two', key=60),
            Trigger(tick=2, ordinal=2, part='left', trigger_id='three', key=61),
        ],
    )
    retirements = [a for a in result.actions if isinstance(a, VoiceRetirement)]
    assert len(retirements) == 1
    assert retirements[0].voice_id == result.actions[1].voice_id
    assert retirements[0].action == action
    assert retirements[0].fade_seconds == (0.25 if mode == 'fade' else None)
    assert any(v.part == 'right' for v in result.snapshots[0].voices)


@pytest.mark.parametrize('kind', ['sample', 'synth'])
@pytest.mark.parametrize('sustain', [False, True])
def test_release_voices_retain_the_onset_pitch(kind: str, sustain: bool) -> None:
    templates = [{'name': 'held'}]
    for trigger in ('release', 'logical_release'):
        template = {'name': trigger, 'trigger': trigger}
        if kind == 'sample':
            template['playback'] = {'mode': 'one_shot'}
        else:
            template['frequency_offset_hz'] = 5
        templates.append(template)
    events = [
        Trigger(
            tick=0,
            ordinal=0,
            part='part',
            trigger_id='note',
            key=60,
            pitch_hz=440,
            velocity=0.6,
            controls={'pedal': 0.75},
        )
    ]
    if sustain:
        events.append(
            ControlChange(
                tick=1, ordinal=1, control='pedal', value=1, scope='part', part='part'
            )
        )
    events.append(Release(tick=2, ordinal=2, part='part', trigger_id='note'))
    if sustain:
        events.append(
            ControlChange(
                tick=3, ordinal=3, control='pedal', value=0, scope='part', part='part'
            )
        )
    result = prepare(
        kind,
        templates,
        events,
        {'controls': {'pedal': {}}, 'sustain': {'control': 'pedal'}},
    )
    starts = [
        a for a in result.actions if a.kind == 'voice_start' and a.template != 'held'
    ]
    assert [a.pitch_hz for a in starts] == [440 if kind == 'sample' else 445] * 2
    assert [a.tick for a in starts] == [2, 3 if sustain else 2]
    contexts = [a for a in result.actions if isinstance(a, TriggerContext)]
    assert len(contexts) == 1
    assert contexts[0].controls == {'pedal': 0.75}
    assert contexts[0].velocity == 0.6


def test_one_shot_survives_ordinary_release() -> None:
    result = prepare(
        'sample',
        [{'name': 'shot', 'playback': {'mode': 'one_shot'}}],
        [
            Trigger(tick=0, ordinal=0, part='part', trigger_id='note', key=60),
            Release(tick=1, ordinal=1, part='part', trigger_id='note'),
        ],
    )
    assert not any(isinstance(a, VoiceRetirement) for a in result.actions)
    assert len(result.snapshots[0].voices) == 1
    assert result.snapshots[0].triggers[0].logical_released


@pytest.mark.parametrize('kind', ['sample', 'synth'])
@pytest.mark.parametrize('same_key', ['release', 'replace'])
def test_same_key_policy_keeps_all_new_layers(kind: str, same_key: str) -> None:
    result = prepare(
        kind,
        [{'name': 'a'}, {'name': 'b'}],
        [
            Trigger(tick=0, ordinal=0, part='part', trigger_id='old', key=60),
            Trigger(tick=1, ordinal=1, part='part', trigger_id='new', key=60),
        ],
        {'voice_policy': {'maximum_voices': 2, 'same_key': same_key}},
    )
    assert [v.template for v in result.snapshots[0].voices] == ['a', 'b']
    assert all(v.trigger_id == 'new' for v in result.snapshots[0].voices)
    retired = [a for a in result.actions if isinstance(a, VoiceRetirement)]
    assert len(retired) == 2
    assert all(a.tick == 1 for a in retired)


@pytest.mark.parametrize('kind', ['sample', 'synth'])
def test_oversized_trigger_batch_is_rejected(kind: str) -> None:
    with pytest.raises(ValueError, match='trigger batch exceeds maximum_voices'):
        prepare(
            kind,
            [{'name': 'a'}, {'name': 'b'}],
            [
                Trigger(tick=0, ordinal=0, part='part', trigger_id='note', key=60),
            ],
            {'voice_policy': {'maximum_voices': 1}},
        )


@pytest.mark.parametrize('kind', ['sample', 'synth'])
def test_preparation_rejects_unimplemented_articulations(kind: str) -> None:
    with pytest.raises(ValueError, match='articulation preparation is unsupported'):
        prepare(
            kind,
            [{'name': 'voice'}],
            [],
            {'articulations': {'ids': ['normal'], 'default': 'normal'}},
        )


def test_synth_action_serialization_preserves_voice_settings() -> None:
    result = prepare(
        'synth',
        [
            {
                'name': 'voice',
                'minimum_hold_seconds': '1/4',
                'synchronize_oscillator': True,
            }
        ],
        [
            Trigger(tick=0, ordinal=0, part='part', trigger_id='note', key=60),
        ],
    )
    restored = synth_trace.SynthTrace.model_validate_json(result.model_dump_json())
    assert restored == result
    assert restored.actions[1].settings.minimum_hold_seconds == 0.25
    assert restored.actions[1].settings.synchronize_oscillator


@pytest.mark.parametrize('kind', ['sample', 'synth'])
def test_voice_ids_distinguish_component_boundaries_and_reused_onsets(
    kind: str,
) -> None:
    result = prepare(
        kind,
        [{'name': 'voice'}],
        [
            Trigger(tick=0, ordinal=0, part='a-b', trigger_id='c', key=60),
            Trigger(tick=1, ordinal=1, part='a', trigger_id='b-c', key=60),
            Release(tick=2, ordinal=2, part='a-b', trigger_id='c'),
            Trigger(tick=3, ordinal=3, part='a-b', trigger_id='c', key=60),
            Release(tick=4, ordinal=4, part='a-b', trigger_id='c'),
        ],
    )
    starts = [a for a in result.actions if a.kind == 'voice_start']
    assert len({a.voice_id for a in starts}) == 3
    retired = [a.voice_id for a in result.actions if isinstance(a, VoiceRetirement)]
    assert retired == [starts[0].voice_id, starts[2].voice_id]


@pytest.mark.parametrize('kind', ['sample', 'synth'])
def test_active_trigger_identity_cannot_be_reused(kind: str) -> None:
    with pytest.raises(ValueError, match='trigger ID is still active'):
        prepare(
            kind,
            [{'name': 'voice'}],
            [
                Trigger(tick=0, ordinal=0, part='part', trigger_id='note', key=60),
                Trigger(tick=1, ordinal=1, part='part', trigger_id='note', key=60),
            ],
        )


@pytest.mark.parametrize('kind', ['sample', 'synth'])
@pytest.mark.parametrize('control,value', [('unknown', 1), ('pedal', -1)])
def test_preparation_validates_control_changes(
    kind: str, control: str, value: float
) -> None:
    with pytest.raises(ValueError):
        prepare(
            kind,
            [{'name': 'voice'}],
            [
                ControlChange(
                    tick=0,
                    ordinal=0,
                    scope='part',
                    part='part',
                    control=control,
                    value=value,
                ),
            ],
            {'controls': {'pedal': {}}},
        )


@pytest.mark.parametrize('kind', ['sample', 'synth'])
def test_snapshot_uses_processed_event_order(kind: str) -> None:
    result = prepare(
        kind,
        [{'name': 'voice'}],
        [
            Release(tick=10, ordinal=1, part='part', trigger_id='note'),
            Trigger(tick=0, ordinal=0, part='part', trigger_id='note', key=60),
        ],
    )
    assert result.snapshots[0].tick == 10
    assert result.snapshots[0].ordinal == 1
    assert not result.snapshots[0].voices


@pytest.mark.parametrize('kind', ['sample', 'synth'])
def test_preparation_rejects_duplicate_event_coordinates(kind: str) -> None:
    event = Trigger(tick=0, ordinal=0, part='part', trigger_id='note', key=60)
    with pytest.raises(ValueError, match='duplicate event coordinate'):
        prepare(kind, [{'name': 'voice'}], [event, event])


@pytest.mark.parametrize('kind', ['sample', 'synth'])
def test_control_context_conformance(kind: str) -> None:
    case = CONTROL_CASES['context']
    events = TypeAdapter(list[PerformanceEvent]).validate_python(case['events'])
    result = prepare(kind, case['templates'], events, case['settings'])
    assert len(result.actions) == len(case['actions'])
    for action, expected in zip(result.actions, case['actions'], strict=True):
        actual = action.model_dump(mode='json')
        assert {k: actual[k] for k in expected} == expected
    assert type(result).model_validate_json(result.model_dump_json()) == result


def test_synth_pitch_applies_offset_and_routed_tuning_once() -> None:
    case = CONTROL_CASES['pitch']['synth']
    target = {'name': 'processing', 'parameter': 'tuning_cents'}
    result = prepare(
        'synth',
        [
            {
                'name': 'voice',
                'frequency_offset_hz': case['offset_hz'],
                'processing': {'tuning_cents': case['static_cents']},
                'modulation': {
                    'parameters': [
                        {
                            'target': target,
                            'unit': 'cents',
                            'scope': 'voice',
                            'minimum': -2400,
                            'maximum': 2400,
                            'default': case['static_cents'],
                        }
                    ],
                    'sources': [
                        {'name': 'bend', 'scope': 'trigger', 'minimum': 0, 'maximum': 1}
                    ],
                    'routes': [
                        {
                            'name': 'bend',
                            'source': 'bend',
                            'target': target,
                            'operation': 'add',
                            'unit': 'cents',
                            'points': [
                                {'input': 0, 'amount': 0},
                                {'input': 1, 'amount': case['route_maximum_cents']},
                            ],
                        }
                    ],
                },
                'bindings': [
                    {
                        'name': 'bend',
                        'kind': 'control',
                        'control': 'bend',
                        'smoothing': '0',
                    }
                ],
            }
        ],
        [
            Trigger(
                tick=0,
                ordinal=0,
                part='main',
                trigger_id='note',
                key=60,
                pitch_hz=case['onset_hz'],
                controls={'bend': case['source_value']},
            )
        ],
        {'controls': {'bend': {}}},
    )
    context, voice = result.actions
    assert isinstance(voice, synth_trace.VoiceStart)
    assert voice.pitch_hz == case['prepared_hz']
    values = modulation.evaluate(
        voice.settings.modulation,
        {'bend': modulation.SourceValue(value=context.controls['bend'])},
    )
    assert values[0].value == case['resolved_cents']
    assert synth.frequency(voice.pitch_hz, values[0].value) == pytest.approx(
        case['frequency_hz'], abs=CONTROL_CASES['absolute_tolerance'], rel=0
    )


def prepare(
    kind: str,
    templates: list[dict[str, object]],
    events: list[PerformanceEvent],
    settings: dict[str, object] | None = None,
) -> trace.SampleTrace | synth_trace.SynthTrace:
    values = [
        {
            'mapping': {'lowest_key': 0, 'highest_key': 127, 'pitch_tracking': False},
            'channels': [{'input': 'mono', 'output': 'mono', 'gain': 1}],
            **v,
        }
        for v in templates
    ]
    if kind == 'synth':
        instrument = SynthInstrument.model_validate(
            {
                **(settings or {}),
                'voices': [{'oscillator': {}, **v} for v in values],
            }
        )
        return synth_trace.prepare(instrument, events, seed=42)
    instrument = SampleInstrument.model_validate(
        {
            'settings': settings or {},
            'slices': [{'name': 'sample', 'asset': 'sample', 'end_frame': 48000}],
            'slots': [{'slice': 'sample', **v} for v in values],
        }
    )
    return trace.prepare(instrument, events, seed=42)


CONTROL_CASES = json.loads(
    (Path(__file__).parents[1] / 'conformance/control-evolution.json').read_text()
)
