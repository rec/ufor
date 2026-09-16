import pytest
from pydantic import TypeAdapter, ValidationError

from ufor import modulation
from ufor.events import ControlChange, Release, Trigger
from ufor.samples import crossfade, playback, processing, selection, trace
from ufor.samples.instrument import (
    Instrument,
    SampleInstrument,
    effective_selection,
    effective_settings,
)


@pytest.mark.parametrize(
    'input_settings',
    [
        {'input': 'key'},
        {'input': 'velocity'},
        {'input': 'control', 'control': 'expression'},
        {'input': 'control', 'control': 'pressure', 'scope': 'instrument'},
        {'input': 'control', 'control': 'pressure', 'scope': 'trigger'},
    ],
)
def test_each_crossfade_input_roundtrips(input_settings: dict[str, object]) -> None:
    raw = {'start': 0, 'end': 1, 'direction': 'in', **input_settings}
    adapter = TypeAdapter(crossfade.LayerCrossfade)
    fade = adapter.validate_python(raw)
    assert adapter.validate_json(fade.model_dump_json()) == fade
    assert fade.model_dump(mode='json', exclude_unset=True) == raw


@pytest.mark.parametrize(
    'changes',
    [
        {'input': 'lfo', 'source': 'vibrato'},
        {'input': 'velocity', 'start': -0.1, 'end': 1},
        {'input': 'key', 'start': 0.5},
        {'input': 'key', 'start': 100, 'end': 10},
        {'input': 'key', 'scope': 'part'},
        {'input': 'control'},
        {'input': 'control', 'control': 'pressure', 'scope': 'voice'},
    ],
)
def test_invalid_crossfades_are_rejected(changes: dict[str, object]) -> None:
    raw = {'input': 'key', 'start': 0, 'end': 127, 'direction': 'out', **changes}
    with pytest.raises(ValidationError):
        TypeAdapter(crossfade.LayerCrossfade).validate_python(raw)


def test_articulation_bindings_have_unique_keys_and_disjoint_ranges() -> None:
    key = {'key': 24, 'articulation': 'a'}
    control = {
        'control': 'style',
        'minimum_value': 0,
        'maximum_value': 0.5,
        'articulation': 'a',
    }
    raw = {'ids': ['a'], 'default': 'a', 'keys': [key], 'controls': [control]}
    selection.Articulations.model_validate(raw)
    with pytest.raises(ValidationError, match='keyswitch'):
        selection.Articulations.model_validate({**raw, 'keys': [key, key]})
    with pytest.raises(ValidationError, match='Overlapping'):
        selection.Articulations.model_validate(
            {
                **raw,
                'controls': [
                    control,
                    {**control, 'minimum_value': 0.5, 'maximum_value': 1},
                ],
            }
        )
    selection.Articulations.model_validate(
        {
            **raw,
            'controls': [
                control,
                {**control, 'minimum_value': 0.6, 'maximum_value': 1},
            ],
        }
    )


def test_articulation_ranges_use_declared_control_domains() -> None:
    raw = {
        'controls': {'style': {}},
        'articulations': {
            'ids': ['soft'],
            'default': 'soft',
            'controls': [
                {
                    'control': 'style',
                    'minimum_value': -1.0,
                    'maximum_value': 0.0,
                    'articulation': 'soft',
                }
            ],
        },
    }
    with pytest.raises(ValidationError, match='must be in'):
        Instrument.model_validate(raw)
    Instrument.model_validate({**raw, 'controls': {'style': {'polarity': 'bipolar'}}})


@pytest.mark.parametrize(
    'raw',
    [
        {'maximum_voices': 12},
        {'maximum_voices': 12, 'same_key': 'release'},
        {'maximum_voices': 12, 'same_key': 'replace', 'overflow': 'replace_oldest'},
    ],
)
def test_voice_policy_round_trips(raw: dict[str, object]) -> None:
    policy = selection.VoicePolicy.model_validate(raw)
    assert selection.VoicePolicy.model_validate_json(policy.model_dump_json()) == policy
    assert policy.model_dump(mode='json', exclude_unset=True) == raw
    assert Instrument.model_validate({'voice_policy': raw}).voice_policy == policy


@pytest.mark.parametrize(
    'raw',
    [
        {},
        {'maximum_voices': 0},
        {'maximum_voices': True},
        {'maximum_voices': 1.5},
        {'maximum_voices': 1, 'same_key': 'restart'},
        {'maximum_voices': 1, 'overflow': 'newest'},
    ],
)
def test_voice_policy_rejects_invalid_values(raw: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        selection.VoicePolicy.model_validate(raw)


def test_random_selection_is_reproducible_and_part_local() -> None:
    takes = selection.Selection(name='takes', mode='random')
    state = selection.SelectionState(seed=42)
    choices = []
    for _ in range(4):
        choice, state = selection.choose(
            takes, state, 'piano', 'start', 60, ['take-c', 'take-a', 'take-b']
        )
        choices.append(choice)
    replay = selection.SelectionState(seed=42)
    replayed = []
    for _ in range(4):
        choice, replay = selection.choose(
            takes, replay, 'piano', 'start', 60, ['take-a', 'take-b', 'take-c']
        )
        replayed.append(choice)
    assert replayed == choices
    other, _ = selection.choose(
        takes, selection.SelectionState(seed=42), 'drums', 'start', 60, ['take-a']
    )
    assert other == 'take-a'
    choice, restored = selection.choose(
        takes, state, 'piano', 'start', 60, ['take-a', 'take-b', 'take-c']
    )
    replay_choice, replay_state = selection.choose(
        takes, replay, 'piano', 'start', 60, ['take-a', 'take-b', 'take-c']
    )
    assert choice == replay_choice
    assert restored == replay_state


def test_shuffle_selection_visits_every_candidate_before_refilling() -> None:
    takes = selection.Selection(name='takes', mode='shuffle')
    state = selection.SelectionState(seed=42)
    choices = []
    for _ in range(6):
        choice, state = selection.choose(
            takes, state, 'piano', 'start', 60, ['take-a', 'take-b', 'take-c']
        )
        choices.append(choice)
    assert set(choices[:3]) == {'take-a', 'take-b', 'take-c'}
    assert set(choices[3:]) == {'take-a', 'take-b', 'take-c'}
    assert choices[2] != choices[3]


def test_selection_state_requires_canonical_sequences() -> None:
    with pytest.raises(ValidationError, match='sorted'):
        selection.SelectionSequence(
            part='piano',
            selection='takes',
            trigger='start',
            key=60,
            candidates=['take-b', 'take-a'],
        )


def test_random_ranges_share_one_value_per_input_event() -> None:
    raw = document()
    raw['slots'][0].update(
        {'name': 'wide', 'random_range': {'minimum': 0.8, 'maximum': 1}}
    )
    narrow = raw['slots'][0].copy()
    narrow.update(
        {
            'name': 'narrow',
            'random_range': {'minimum': 0.9, 'maximum': 1},
        }
    )
    gap = raw['slots'][0].copy()
    gap.update({'name': 'gap', 'random_range': {'minimum': 0, 'maximum': 0.8}})
    raw['slots'].extend([narrow, gap])
    result = trace.prepare(
        SampleInstrument.model_validate(raw),
        [Trigger(tick=0, ordinal=0, part='piano', trigger_id='note-a', key=60)],
        seed=42,
    )
    assert [
        action.template
        for action in result.actions
        if isinstance(action, trace.VoiceStart)
    ] == ['wide', 'narrow']


def test_slot_group_inherits_whole_sound_settings_and_selection() -> None:
    group = {
        'name': 'close',
        'selection': 'takes',
        'processing': {'volume_db': -6},
    }
    raw = document(
        instrument={'selections': [{'name': 'takes', 'mode': 'cycle'}]},
        slot={'group': 'close'},
    )
    raw['groups'] = [group]
    instrument = SampleInstrument.model_validate(raw)
    slot = instrument.slots[0]
    assert effective_selection(slot, instrument.groups[0]) == 'takes'
    assert effective_settings(slot, instrument.groups[0]).processing.volume_db == -6
    overridden = slot.model_copy(
        update={'selection': False, 'processing': {'volume_db': 0}}
    )
    assert effective_selection(overridden, instrument.groups[0]) is None
    assert (
        effective_settings(overridden, instrument.groups[0]).processing.volume_db == 0
    )


def test_linked_microphone_takes_share_a_selection_identity() -> None:
    raw = document(instrument={'selections': [{'name': 'takes', 'mode': 'cycle'}]})
    slots = []
    for take in ('strike-a', 'strike-b'):
        for microphone in ('close', 'room'):
            slot = raw['slots'][0].copy()
            slot.update(
                {
                    'name': f'{take}-{microphone}',
                    'selection': 'takes',
                    'take': take,
                    'microphone': microphone,
                    'alignment_frames': -12 if microphone == 'room' else 0,
                }
            )
            slots.append(slot)
    raw['slots'] = slots
    instrument = SampleInstrument.model_validate(raw)
    assert {s.take for s in instrument.slots} == {'strike-a', 'strike-b'}
    missing = raw.copy()
    missing['slots'] = slots[:-1]
    with pytest.raises(ValidationError, match='different microphones'):
        SampleInstrument.model_validate(missing)


def test_resonant_filter_uses_rbj_coefficients_and_configured_boundaries() -> None:
    filter = processing.ResonantFilter(name='tone', response='lowpass', cutoff_hz=1000)
    coefficients = processing.biquad_coefficients(filter, 48000)
    assert (coefficients.b0 + coefficients.b1 + coefficients.b2) / (
        1 + coefficients.a1 + coefficients.a2
    ) == pytest.approx(1)
    settings = processing.SoundSettings(
        processing=processing.Processing(filters=[filter])
    )
    assert processing.parameter_definition(
        settings, modulation.Target(name='filter-tone', parameter='cutoff_hz')
    ) == (modulation.Unit.hz, 1000)
    with pytest.raises(ValueError, match='rate bounds'):
        processing.biquad_coefficients(
            filter.model_copy(update={'cutoff_hz': 24000}), 48000
        )
    clamped = filter.model_copy(update={'cutoff_hz': 24000, 'boundary': 'clamp'})
    expected = processing.biquad_coefficients(
        clamped.model_copy(update={'cutoff_hz': 48000 * 0.5 * 0.999}), 48000
    )
    assert processing.biquad_coefficients(clamped, 48000) == expected


def test_semantic_trace_round_trips_resolved_voice_actions_and_snapshots() -> None:
    settings = processing.SoundSettings()
    action = trace.VoiceStart(
        tick=0,
        ordinal=0,
        voice_id='voice-1',
        part='piano',
        trigger_id='note-1',
        template='close-a',
        key=60,
        slice='strike-a',
        start_frame=100,
        alignment_frames=-12,
        channels=[processing.ChannelRoute(input='mono', output='left', gain=1)],
        settings=settings,
    )
    snapshot = trace.TraceSnapshot(
        tick=0,
        ordinal=0,
        selection=selection.SelectionState(seed=42),
        voices=[
            trace.ActiveVoice(
                voice_id='voice-1',
                part='piano',
                trigger_id='note-1',
                template='close-a',
                key=60,
            )
        ],
    )
    value = trace.SemanticTrace(seed=42, actions=[action], snapshots=[snapshot])
    assert trace.SemanticTrace.model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValidationError, match='ordered'):
        trace.SemanticTrace(
            seed=42, actions=[action, action.model_copy(update={'tick': -1})]
        )


def test_prepare_emits_linked_start_release_and_unknown_release_actions() -> None:
    raw = document(instrument={'selections': [{'name': 'takes', 'mode': 'cycle'}]})
    raw['slots'][0].update(
        {
            'selection': 'takes',
            'take': 'hit-a',
            'microphone': 'close',
            'variation': {
                'delay_seconds': 0.01,
                'offset_frames': 20,
                'pitch_cents': 5,
                'gain_db': 1,
            },
        }
    )
    room = raw['slots'][0].copy()
    room.update({'name': 'room-a', 'microphone': 'room', 'alignment_frames': -12})
    raw['slots'].append(room)
    instrument = SampleInstrument.model_validate(raw)
    result = trace.prepare(
        instrument,
        [
            Trigger(tick=0, ordinal=0, part='piano', trigger_id='note-a', key=60),
            Release(tick=1, ordinal=1, part='piano', trigger_id='note-a'),
            Release(tick=2, ordinal=2, part='piano', trigger_id='missing'),
        ],
        seed=42,
    )
    assert [action.kind for action in result.actions] == [
        'voice_start',
        'voice_start',
        'voice_retirement',
        'voice_retirement',
        'diagnostic',
    ]
    assert result.actions[1].alignment_frames == -12
    assert result.actions[0].variation == result.actions[1].variation
    assert result.actions[-1].code == 'unknown-release'


def test_prepare_keeps_repeated_keys_until_their_first_releases() -> None:
    raw = document()
    raw['slots'][0]['name'] = 'start'
    release = raw['slots'][0].copy()
    release.update(
        {'name': 'release', 'trigger': 'release', 'playback': {'mode': 'one_shot'}}
    )
    logical_release = raw['slots'][0].copy()
    logical_release.update(
        {
            'name': 'logical-release',
            'trigger': 'logical_release',
            'playback': {'mode': 'one_shot'},
        }
    )
    raw['slots'].extend([release, logical_release])
    result = trace.prepare(
        SampleInstrument.model_validate(raw),
        [
            Trigger(tick=0, ordinal=0, part='piano', trigger_id='first', key=60),
            Trigger(tick=1, ordinal=1, part='piano', trigger_id='second', key=60),
            Release(tick=2, ordinal=2, part='piano', trigger_id='second'),
            Release(tick=3, ordinal=3, part='piano', trigger_id='first'),
            Release(tick=4, ordinal=4, part='piano', trigger_id='second'),
        ],
        seed=42,
    )
    starts = [
        action for action in result.actions if isinstance(action, trace.VoiceStart)
    ]
    assert [(action.trigger_id, action.template) for action in starts] == [
        ('first', 'start'),
        ('second', 'start'),
        ('second', 'release'),
        ('second', 'logical-release'),
        ('first', 'release'),
        ('first', 'logical-release'),
    ]
    assert [
        (trigger.trigger_id, trigger.templates, trigger.logical_released)
        for trigger in result.snapshots[0].triggers
    ] == [
        ('first', ['start'], True),
        ('second', ['start'], True),
    ]


def test_prepare_defers_logical_release_and_emits_sustain_crossings() -> None:
    raw = document(
        instrument={'controls': {'sustain': {}}, 'sustain': {'control': 'sustain'}}
    )
    raw['slots'][0]['name'] = 'start'
    for name, trigger, mapping in [
        ('release', 'release', None),
        ('logical-release', 'logical_release', None),
        ('pedal-down', 'sustain_press', {'event_key': 50}),
        ('pedal-up', 'sustain_release', {'event_key': 50}),
    ]:
        slot = raw['slots'][0].copy()
        slot.update(
            {'name': name, 'trigger': trigger, 'playback': {'mode': 'one_shot'}}
        )
        if mapping is not None:
            slot['mapping'] = {**slot['mapping'], **mapping, 'pitch_tracking': False}
        raw['slots'].append(slot)
    result = trace.prepare(
        SampleInstrument.model_validate(raw),
        [
            ControlChange(
                tick=0,
                ordinal=0,
                scope='part',
                part='piano',
                control='sustain',
                value=1,
            ),
            ControlChange(
                tick=1,
                ordinal=1,
                scope='part',
                part='piano',
                control='sustain',
                value=1,
            ),
            Trigger(tick=2, ordinal=2, part='piano', trigger_id='note', key=60),
            Release(tick=3, ordinal=3, part='piano', trigger_id='note'),
            ControlChange(
                tick=4,
                ordinal=4,
                scope='part',
                part='piano',
                control='sustain',
                value=0,
            ),
            ControlChange(
                tick=5,
                ordinal=5,
                scope='part',
                part='piano',
                control='sustain',
                value=0,
            ),
        ],
        seed=42,
    )
    starts = [
        action for action in result.actions if isinstance(action, trace.VoiceStart)
    ]
    assert [(action.trigger_id, action.template) for action in starts] == [
        (None, 'pedal-down'),
        ('note', 'start'),
        ('note', 'release'),
        ('note', 'logical-release'),
        (None, 'pedal-up'),
    ]
    retirements = [
        action for action in result.actions if isinstance(action, trace.VoiceRetirement)
    ]
    assert [(action.tick, action.cause) for action in retirements] == [
        (4, trace.RetirementCause.logical_release)
    ]


def test_prepare_does_not_emit_release_slots_for_a_choked_trigger() -> None:
    raw = document(slot={'name': 'held', 'choke_group': 'held'})
    raw['slots'][0]['mapping']['highest_key'] = 60
    choker = raw['slots'][0].copy()
    choker.update(
        {
            'name': 'choker',
            'mapping': {**choker['mapping'], 'lowest_key': 61, 'highest_key': 61},
            'chokes': [{'group': 'held', 'mode': 'immediate'}],
        }
    )
    release = raw['slots'][0].copy()
    release.update(
        {'name': 'release', 'trigger': 'release', 'playback': {'mode': 'one_shot'}}
    )
    logical_release = release.copy()
    logical_release.update({'name': 'logical-release', 'trigger': 'logical_release'})
    raw['slots'].extend([choker, release, logical_release])
    result = trace.prepare(
        SampleInstrument.model_validate(raw),
        [
            Trigger(tick=0, ordinal=0, part='piano', trigger_id='first', key=60),
            Trigger(tick=1, ordinal=1, part='piano', trigger_id='second', key=61),
            Release(tick=2, ordinal=2, part='piano', trigger_id='first'),
        ],
        seed=42,
    )
    starts = [
        action for action in result.actions if isinstance(action, trace.VoiceStart)
    ]
    assert [(action.trigger_id, action.template) for action in starts] == [
        ('first', 'held'),
        ('second', 'choker'),
    ]


def test_pitch_tracking_uses_a_reference_frequency_not_selection_key() -> None:
    mapping = playback.Mapping(
        lowest_key=-200, highest_key=10000, reference_pitch_hz=443.123456
    )
    assert mapping.reference_pitch_hz == 443.123456
    with pytest.raises(ValidationError, match='reference_pitch_hz'):
        playback.Mapping(lowest_key=0, highest_key=127)
    assert (
        playback.Mapping(
            lowest_key=0, highest_key=127, pitch_tracking=False
        ).reference_pitch_hz
        is None
    )


def test_release_and_sustain_slots_can_inherit_one_shot() -> None:
    for trigger in ('release', 'logical_release'):
        SampleInstrument.model_validate(
            document(
                slot={'trigger': trigger}, instrument={'playback': {'mode': 'one_shot'}}
            )
        )
    mapping = {
        'lowest_key': 60,
        'highest_key': 60,
        'event_key': 60,
        'pitch_tracking': False,
    }
    for trigger in ('sustain_press', 'sustain_release'):
        SampleInstrument.model_validate(
            document(
                slot={'trigger': trigger, 'mapping': mapping},
                instrument={
                    'playback': {'mode': 'one_shot'},
                    'controls': {'sustain': {}},
                    'sustain': {'control': 'sustain'},
                },
            )
        )
    with pytest.raises(ValidationError, match='require a sustain control'):
        SampleInstrument.model_validate(
            document(
                slot={'trigger': 'sustain_press', 'mapping': mapping},
                instrument={
                    'playback': {'mode': 'one_shot'},
                },
            )
        )


@pytest.mark.parametrize(
    ('trigger', 'mapping'),
    [
        ('sustain_press', {'pitch_tracking': False}),
        ('sustain_press', {'pitch_tracking': False, 'event_key': 100}),
        ('sustain_release', {'reference_pitch_hz': 440, 'event_key': 60}),
        ('start', {'pitch_tracking': False, 'event_key': 60}),
    ],
)
def test_sustain_event_keys_are_contained_untracked_and_not_ordinary_keys(
    trigger: str, mapping: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        SampleInstrument.model_validate(
            document(
                slot={
                    'trigger': trigger,
                    'mapping': {'lowest_key': 48, 'highest_key': 84, **mapping},
                },
                instrument={
                    'playback': {'mode': 'one_shot'},
                    'controls': {'sustain': {}},
                    'sustain': {'control': 'sustain'},
                },
            )
        )


def test_cross_references_and_sustain_alternative_keys() -> None:
    raw = document(
        instrument={
            'selections': [{'name': 'takes', 'mode': 'cycle'}],
            'playback': {'mode': 'one_shot'},
            'controls': {'sustain': {}},
            'sustain': {'control': 'sustain'},
        },
        slot={
            'selection': 'takes',
            'choke_group': 'tails',
            'chokes': [{'group': 'tails', 'mode': 'immediate'}],
            'trigger': 'sustain_press',
            'mapping': {
                'lowest_key': 48,
                'highest_key': 84,
                'event_key': 60,
                'pitch_tracking': False,
            },
        },
    )
    instrument = SampleInstrument.model_validate(raw)
    second = instrument.slots[0].model_dump(exclude_unset=True)
    second['name'] = 'second'
    raw['slots'].append(second)
    SampleInstrument.model_validate(raw)
    second['mapping'] = {
        'lowest_key': 48,
        'highest_key': 84,
        'event_key': 61,
        'pitch_tracking': False,
    }
    with pytest.raises(ValidationError, match='share event_key'):
        SampleInstrument.model_validate(raw)
    second['name'] = 'glass'
    with pytest.raises(ValidationError, match='duplicate slot ID'):
        SampleInstrument.model_validate(raw)


def test_unknown_fields_and_old_bank_key_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SampleInstrument.model_validate({**document(), 'bank': {}})
    with pytest.raises(ValidationError):
        SampleInstrument.model_validate(document(slot={'playback': {'typo': 1}}))


def document(
    slot: dict[str, object] | None = None, instrument: dict[str, object] | None = None
) -> dict[str, object]:
    return {
        'kind': 'sample_instrument',
        'slices': [{'name': 'glass', 'asset': 'glass', 'end_frame': 48000}],
        'instrument': instrument or {},
        'slots': [
            {
                'name': 'glass',
                'slice': 'glass',
                'channels': [{'input': 'mono', 'output': 'mono', 'gain': 1}],
                'mapping': {
                    'lowest_key': 48,
                    'highest_key': 84,
                    'reference_pitch_hz': 60,
                },
                **(slot or {}),
            }
        ],
    }
