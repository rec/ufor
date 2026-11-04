import pytest
from pydantic import ValidationError
from test_synth import fixture

from ufor.codec import parse_score, score_schema, score_toml
from ufor.dx7 import DX7ControllerAssignment, DX7Performance
from ufor.events import Release, Trigger
from ufor.synth import SynthInstrumentScore, YamahaDX7Voice, YamahaTX81ZVoice
from ufor.synth_trace import SynthTrace, VoiceStart, prepare


@pytest.mark.parametrize('kind,size', [('dx7', 155), ('dx7', 128), ('tx81z', 93)])
def test_yamaha_patches_and_release_velocity_survive_portable_round_trips(
    kind: str, size: int
) -> None:
    raw = fixture()
    previous = raw['body']['voices'][0]
    payload = bytes(i % 128 for i in range(size))
    template = {
        'name': 'yamaha',
        'mapping': previous['mapping'],
        'channels': previous['channels'],
        'yamaha': kind,
        'patch': payload.hex(),
    }
    if kind == 'tx81z':
        template['additional'] = bytes(range(23)).hex()
    else:
        template['performance'] = {
            'pitch_bend_range': 12,
            'modulation_wheel': {'range': 99, 'pitch': True},
            'breath': {'range': 75, 'amplitude': True, 'eg_bias': True},
            'foot': {'range': 25, 'pitch': True, 'amplitude': True},
        }
    raw['body']['voices'] = [
        template,
        {**template, 'name': 'release', 'trigger': 'release'},
    ]
    score = SynthInstrumentScore.model_validate(raw)
    assert parse_score(score_toml(score)) == score
    assert SynthInstrumentScore.model_validate_json(score.model_dump_json()) == score
    assert isinstance(
        score.body.voices[0], YamahaDX7Voice if kind == 'dx7' else YamahaTX81ZVoice
    )
    assert score.body.voices[0].patch.data == payload
    assert (
        score_schema()['$defs']['YamahaDX7Voice']['properties']['patch']['type']
        == 'string'
    )
    result = prepare(
        score.body,
        [
            Trigger(
                tick=0,
                ordinal=0,
                part='main',
                trigger_id='note',
                key=69,
                velocity=0.25,
                pitch_hz=445,
            ),
            Release(tick=10, ordinal=0, part='main', trigger_id='note'),
        ],
        seed=0,
    )
    assert SynthTrace.model_validate_json(result.model_dump_json()) == result
    starts = [a for a in result.actions if isinstance(a, VoiceStart)]
    assert [a.velocity for a in starts] == [0.25, 0.25]
    assert all(a.pitch_hz == 445 and a.oscillator is None for a in starts)
    assert all(a.settings.patch.data == payload for a in starts)
    if kind == 'dx7':
        assert all(
            a.settings.performance == DX7Performance(**template['performance'])
            for a in starts
        )


def test_dx7_performance_defaults_leave_controller_assignments_disabled() -> None:
    previous = fixture()['body']['voices'][0]
    voice = YamahaDX7Voice(
        name='voice',
        mapping=previous['mapping'],
        channels=previous['channels'],
        patch=bytes(155).hex(),
    )
    assert voice.performance.pitch_bend_range == 2
    for a in (
        voice.performance.modulation_wheel,
        voice.performance.breath,
        voice.performance.foot,
    ):
        assert a.range == 0
        assert not (a.pitch or a.amplitude or a.eg_bias)


@pytest.mark.parametrize('value', [-1, 100, 0.5, True])
def test_dx7_performance_rejects_invalid_hardware_ranges(value: object) -> None:
    with pytest.raises(ValidationError):
        DX7ControllerAssignment(range=value)
    with pytest.raises(ValidationError):
        DX7Performance(pitch_bend_range=value)
    with pytest.raises(ValidationError):
        DX7Performance(pitch_bend_range=13)


def test_tx81z_template_requires_explicit_additional_buffer() -> None:
    with pytest.raises(ValidationError, match='additional'):
        YamahaTX81ZVoice(
            name='voice',
            mapping={'reference_pitch_hz': 440},
            channels=[{'input': 'mono', 'output': 'left'}],
            patch=bytes(93).hex(),
        )


@pytest.mark.parametrize('kind', ['dx7', 'tx81z'])
@pytest.mark.parametrize(
    'controller', ['pitch_bend', 'modulation_wheel', 'breath', 'foot']
)
def test_yamaha_controller_targets_round_trip_with_bounded_domains(
    kind: str, controller: str
) -> None:
    raw = fixture()
    previous = raw['body']['voices'][0]
    template = {
        'name': 'yamaha',
        'mapping': previous['mapping'],
        'channels': previous['channels'],
        'yamaha': kind,
        'patch': bytes(155 if kind == 'dx7' else 93).hex(),
        'modulation': {
            'parameters': [
                {
                    'target': {'name': 'yamaha', 'parameter': controller},
                    'unit': 'ratio',
                    'scope': 'voice',
                    'minimum': -1 if controller == 'pitch_bend' else 0,
                    'maximum': 1,
                    'default': 0,
                }
            ]
        },
    }
    if kind == 'tx81z':
        template['additional'] = bytes(23).hex()
    raw['body']['voices'] = [template]
    score = SynthInstrumentScore.model_validate(raw)
    assert parse_score(score_toml(score)) == score
    assert SynthInstrumentScore.model_validate_json(score.model_dump_json()) == score
    parameter = template['modulation']['parameters'][0]
    for field, value in [
        ('minimum', -2),
        ('maximum', 2),
        ('default', 0.5),
        ('unit', 'cents'),
    ]:
        original = parameter[field]
        parameter[field] = value
        with pytest.raises(ValidationError):
            SynthInstrumentScore.model_validate(raw)
        parameter[field] = original
    parameter['target']['parameter'] = 'unknown_controller'
    with pytest.raises(ValidationError):
        SynthInstrumentScore.model_validate(raw)
