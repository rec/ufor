import pytest
from pydantic import TypeAdapter, ValidationError

from ufor.samples import crossfade, playback, selection
from ufor.samples.instrument import (
    Instrument,
    SampleInstrument,
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
