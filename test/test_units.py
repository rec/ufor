import json
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError
from reccy.configuration import units

from ufor import base
from ufor.arpeggiator import Grid
from ufor.assets import ContentIdentity
from ufor.automation import TimelineCurve
from ufor.broadcast import ProgrammeSource
from ufor.codec import parse_score, score_toml
from ufor.control import TempoPoint
from ufor.effects import ExpandingRipples, Hamiltonian, Interference, SaberBlade
from ufor.lfo import LFO
from ufor.light_animation import Fade
from ufor.lights import Layout
from ufor.modulation import Parameter, Route
from ufor.motion import (
    Affine,
    Cycle,
    MotionParameter,
    MotionScore,
    MotionUse,
    instantiate_motion,
)
from ufor.samples.playback import Slice
from ufor.samples.variation import Variation
from ufor.segments import Segment
from ufor.slideshow import Slide
from ufor.time import Rate
from ufor.tuning import FrequencyTable, Tuning

CASES = json.loads(Path('conformance/units.json').read_text())


@pytest.mark.parametrize('case', CASES['valid'])
def test_portable_unit_conversions_preserve_exact_values(case: dict[str, str]) -> None:
    assert units.magnitude(case['authored'], case['unit'], exact=True) == Fraction(
        case['canonical']
    )


@pytest.mark.parametrize('case', CASES['invalid'])
def test_portable_unit_conversions_reject_incompatible_dimensions(
    case: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        units.magnitude(case['authored'], case['unit'], exact=True)


def test_fixed_units_normalize_without_changing_the_numeric_contract() -> None:
    assert TypeAdapter(base.Frequency).validate_python('2kHz') == 2000
    assert TypeAdapter(base.Seconds).validate_python('250ms') == 0.25
    assert Rate(numerator='48kHz').numerator == 48000
    assert ContentIdentity(byte_length='2KiB', sha256='0' * 64).byte_length == 2048
    region = Slice(
        name='region',
        asset='audio',
        start_frame='9007199254740993 frame',
        end_frame='9007199254740994 frame',
    )
    assert region.start_frame == 9007199254740993
    variation = Variation(
        pitch_cents='1 semitone', gain_db='6dB', delay_seconds='250ms'
    )
    assert variation.pitch_cents == 100
    assert variation.gain_db == 6
    assert variation.delay_seconds == 0.25


def test_authored_timing_stays_exact_and_serializes_in_canonical_units() -> None:
    point = TempoPoint(at_seconds='1/3 ms', beat='1/4 beat', bpm='2 beat/s')
    assert point.at_seconds == Fraction(1, 3000)
    assert point.beat == Fraction(1, 4)
    assert point.bpm == 120
    assert Fade(duration='1/3 ms').duration == Fraction(1, 3000)
    segment = Segment(duration='1/3ms', to=1)
    assert segment.duration == Fraction(1, 3000)
    assert segment.model_dump()['duration'] == '1/3000 s'


@pytest.mark.parametrize(
    ('authored', 'serialized'),
    [('1 ms / 3', '1/3000 s'), ('1000 millibeats / 3', '1/3 beat')],
)
def test_segment_expressions_select_their_clock_and_round_trip(
    authored: str, serialized: str
) -> None:
    segment = Segment(duration=authored, to=1)
    assert segment.model_dump()['duration'] == serialized
    assert Segment.model_validate(segment.model_dump()) == segment


def test_rhythmic_steps_and_tuning_accept_pint_expressions() -> None:
    assert Grid(step='1000 millibeat / 3').step == '1/3 beat'
    tuning = Tuning(source={'kind': 'computed'}, root_frequency='880 Hz / 2')
    assert tuning.root_frequency == '440'
    assert (
        Tuning(
            source={'kind': 'computed'}, root_frequency='440/2^(1/12)'
        ).root_frequency
        == '440/2^(1/12)'
    )


@pytest.mark.parametrize(
    ('unit', 'authored'),
    [
        ('ratio', '90degree'),
        ('normalized', '-6dB'),
        ('logical', '1 semitone'),
        ('radians', '50%'),
    ],
)
def test_parameter_inputs_reject_other_semantic_families(
    unit: str, authored: str
) -> None:
    with pytest.raises(ValidationError):
        Parameter(
            target={'name': 'control', 'parameter': 'value'},
            unit=unit,
            scope='voice',
            minimum=-1,
            maximum=1,
            default=authored,
        )


def test_patch_offsets_remain_dimensionless_numbers() -> None:
    with pytest.raises(ValidationError):
        Affine(input='source', offset='1 volt')


def test_unit_strings_obey_integer_and_positive_constraints() -> None:
    for v in ['0Hz', '-1Hz', '2ms', True]:
        with pytest.raises(ValidationError):
            TypeAdapter(base.Frequency).validate_python(v)
    for v in ['1.5 frame', '1s', True, 1.5]:
        with pytest.raises(ValidationError):
            TypeAdapter(base.Frame).validate_python(v)


def test_relay_buffer_uses_positive_programme_ticks() -> None:
    source = ProgrammeSource(name='relay', kind='relay', relay_buffer='48000tick')
    assert source.relay_buffer == 48000
    for v in ['1s', '1KiB', '0tick', '1.5tick']:
        with pytest.raises(ValidationError):
            ProgrammeSource(name='relay', kind='relay', relay_buffer=v)


def test_lfo_and_nested_motion_use_their_declared_clock() -> None:
    lfo = LFO(clock='beats', rate='2/beat', delay='1/3 beat', phase='90degree')
    assert lfo.rate == 2
    assert lfo.delay == Fraction(1, 3)
    assert lfo.phase == Fraction(1, 4)
    motion = MotionUse(
        clock='beats', body={'kind': 'cycle', 'rate': '2/beat', 'delay': '1/3 beat'}
    )
    assert isinstance(motion.body, Cycle)
    assert motion.body.delay == Fraction(1, 3)
    with pytest.raises(ValidationError):
        LFO(clock='beats', rate='2Hz')
    with pytest.raises(ValidationError):
        MotionUse(clock='beats', body={'kind': 'cycle', 'rate': '2Hz'})


def test_parameters_routes_and_automation_use_the_declared_dimension() -> None:
    parameter = Parameter(
        target={'name': 'filter', 'parameter': 'cutoff'},
        unit='hz',
        scope='voice',
        minimum='20Hz',
        maximum='20kHz',
        default='1kHz',
    )
    assert parameter.maximum == 20000
    assert parameter.default == 1000
    route = Route(
        name='pitch',
        source='bend',
        target=parameter.target,
        operation='add',
        unit='hz',
        points=[{'input': -1, 'amount': '-1kHz'}, {'input': 1, 'amount': '1kHz'}],
    )
    assert route.points[0].amount == -1000
    curve = TimelineCurve(
        name='sweep',
        unit='hz',
        at='1tick',
        initial='100Hz',
        segments=[{'duration': '2tick', 'to': '1kHz'}],
    )
    assert curve.initial == 100
    assert curve.segments[0].to == 1000


def test_referenced_motion_parameters_normalize_during_preparation() -> None:
    score = MotionScore(
        name='oscillation',
        title='Oscillation',
        parameters={
            'speed': MotionParameter(
                unit='hz', minimum='1Hz', maximum='2kHz', default='1kHz'
            )
        },
        body=Cycle(rate={'parameter': 'speed'}),
    )
    motion = instantiate_motion(score, {'speed': '500Hz'})
    assert isinstance(motion.body, Cycle)
    assert motion.body.rate == 500
    assert parse_score(score_toml(score)) == score


def test_geometry_effects_and_slide_angles_normalize_in_their_own_units() -> None:
    layout = Layout(
        name='stage',
        axes=['x'],
        unit='metres',
        lights=[{'name': 'lamp', 'position': ['2cm']}],
    )
    assert layout.lights[0].position == [0.02]
    ripples = ExpandingRipples(
        propagation_speed='12pixel/s', width='2pixel', decay='3/s'
    )
    assert ripples.propagation_speed == 12
    assert ripples.width == 2
    assert ripples.decay == 3
    interference = Interference(
        wavelengths=['2pixel'], rates=['3radian/s'], phase_offsets=['0radian']
    )
    assert interference.rates == [3]
    assert Hamiltonian(speed='12pixel/s').speed == 12
    assert SaberBlade(speed='2pixel/frame').speed == 2
    with pytest.raises(ValidationError):
        SaberBlade(speed='2pixel/s')
    assert (
        Slide(
            name='slide',
            asset='photo',
            duration='2tick',
            alt='Photo',
            rotation='90degree',
        ).rotation
        == 90
    )
    assert FrequencyTable(values=['2kHz']).frequencies == [2000]
    tuning = Tuning(source={'kind': 'computed'}, root_frequency='2kHz')
    assert tuning.root_frequency == '2000'


def test_fixture_encodings_and_cues_use_the_profile_unit() -> None:
    from ufor.fixture import FixtureShow

    show = FixtureShow(
        profile={
            'name': 'fixture',
            'parameters': [
                {
                    'name': 'pan',
                    'unit': 'radians',
                    'minimum': '0radian',
                    'maximum': '180degree',
                }
            ],
            'channels': [
                {
                    'parameter': 'pan',
                    'slots': [1],
                    'minimum': '0radian',
                    'maximum': '180degree',
                }
            ],
        },
        fixtures=['lamp'],
        cues=[
            {
                'tick': '1tick',
                'ordinal': 0,
                'fixture': 'lamp',
                'parameter': 'pan',
                'value': '90degree',
            }
        ],
    )
    assert show.cues[0].value == pytest.approx(1.5707963267948966)
    assert show.profile.channels[0].maximum == show.profile.parameters[0].maximum


def test_effect_actions_keep_fractional_unit_conversions_and_frame_counts() -> None:
    from ufor.audio_effects import ParameterAction

    action = ParameterAction(
        tick='48000frame',
        ordinal=0,
        processor='delay',
        parameter='delay_seconds',
        value='1/3 ms',
        duration_frames='480frame',
    )
    assert action.value == pytest.approx(1 / 3000)
    assert action.duration_frames == 480
