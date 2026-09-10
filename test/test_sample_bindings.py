from copy import deepcopy
from fractions import Fraction

import pytest
from pydantic import ValidationError

from ufor import envelope, modulation
from ufor.samples.controls import Control
from ufor.samples.instrument import SampleInstrument
from ufor.samples.processing import SoundSettings


def test_sample_routes_use_the_shared_evaluator() -> None:
    settings = SoundSettings.model_validate(lfo_settings())
    values = modulation.evaluate(
        settings.modulation, {'motion': modulation.SourceValue(value=1, weight=0.5)}
    )
    assert values[0].value == 0.25


@pytest.mark.parametrize('kind', ['key', 'velocity', 'control', 'envelope', 'lfo'])
def test_binding_kinds_round_trip_with_their_real_source_definitions(kind: str) -> None:
    raw = lfo_settings()
    binding: dict[str, object] = {'name': 'motion', 'kind': kind}
    source = raw['modulation']['sources'][0]
    if kind == 'control':
        binding['control'] = 'bend'
        source['scope'] = 'part'
    elif kind == 'envelope':
        raw['envelopes'] = {
            'motion': envelope.Envelope(
                segments=[envelope.Segment(duration=1, target=1)],
                release=[envelope.Segment(duration=1, target=0)],
            ).model_dump()
        }
        raw['lfos'] = {}
        binding['reference'] = 'motion'
        source['minimum'] = 0
        raw['modulation']['routes'][0]['points'][0]['input'] = 0
    elif kind == 'velocity':
        source['minimum'] = 0
        raw['modulation']['routes'][0]['points'][0]['input'] = 0
    elif kind == 'lfo':
        binding['reference'] = 'motion'
    raw['bindings'] = [binding]
    result = SoundSettings.model_validate(raw)
    result.validate_controls({'bend': Control.model_validate({'polarity': 'bipolar'})})
    assert SoundSettings.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize(
    ('section', 'changes', 'message'),
    [
        ('source', {'scope': 'instrument'}, 'scope and domain'),
        ('source', {'minimum': -0.5}, 'exceed its source domain'),
        ('binding', {'reference': 'missing'}, 'Unknown local lfo'),
        ('binding', {'kind': 'envelope'}, 'Unknown local envelope'),
        ('binding', {'name': 'unbound'}, 'exactly one binding'),
        ('parameter', {'unit': 'volts'}, 'requires unit'),
        ('parameter', {'default': 0.1}, 'default must match'),
        (
            'parameter',
            {'target': {'name': 'processing', 'parameter': 'unknown'}},
            'unknown source or target',
        ),
    ],
)
def test_bindings_reject_false_domains_names_and_units(
    section: str, changes: dict[str, object], message: str
) -> None:
    raw = lfo_settings()
    item = (
        raw['bindings'][0]
        if section == 'binding'
        else raw['modulation'][
            {'source': 'sources', 'parameter': 'parameters'}[section]
        ][0]
    )
    item.update(changes)
    with pytest.raises(ValidationError, match=message):
        SoundSettings.model_validate(raw)


def test_generator_definitions_are_never_duplicated_between_scopes() -> None:
    raw = lfo_settings()
    raw['envelopes'] = {
        'motion': {
            'segments': [{'duration': 0, 'target': 1}],
            'release': [{'duration': 0, 'target': 0}],
        }
    }
    with pytest.raises(ValidationError, match='duplicate source ID'):
        SoundSettings.model_validate(raw)


def test_bindings_and_route_ids_are_unique() -> None:
    raw = lfo_settings()
    raw['bindings'].append(deepcopy(raw['bindings'][0]))
    with pytest.raises(ValidationError, match='duplicate binding'):
        SoundSettings.model_validate(raw)
    raw = lfo_settings()
    raw['modulation']['routes'].append(deepcopy(raw['modulation']['routes'][0]))
    with pytest.raises(ValidationError, match='duplicate route'):
        SoundSettings.model_validate(raw)


def test_control_bindings_validate_names_domains_and_scopes() -> None:
    raw = lfo_settings()
    raw['bindings'] = [{'name': 'motion', 'kind': 'control', 'control': 'bend'}]
    raw['modulation']['sources'][0]['scope'] = 'part'
    settings = SoundSettings.model_validate(raw)
    with pytest.raises(ValueError, match='Unknown control'):
        settings.validate_controls({})
    with pytest.raises(ValueError, match='declared domain'):
        settings.validate_controls({'bend': Control()})
    settings.validate_controls(
        {'bend': Control.model_validate({'polarity': 'bipolar'})}
    )
    raw['modulation']['sources'][0]['scope'] = 'voice'
    settings = SoundSettings.model_validate(raw)
    with pytest.raises(ValueError, match='control scope'):
        settings.validate_controls(
            {'bend': Control.model_validate({'polarity': 'bipolar'})}
        )


def test_key_curves_require_integer_knots_without_midi_key_limits() -> None:
    raw = lfo_settings()
    raw['bindings'] = [{'name': 'motion', 'kind': 'key'}]
    raw['modulation']['sources'][0].update(minimum=-200, maximum=10000)
    SoundSettings.model_validate(raw)
    raw['modulation']['routes'][0]['points'][0]['input'] = 0.5
    with pytest.raises(ValidationError, match='must be integers'):
        SoundSettings.model_validate(raw)


def test_envelope_segment_targets_use_the_declared_clock_and_latch_inputs() -> None:
    definition = envelope.Envelope.model_validate(
        {
            'clock': 'beats',
            'segments': [{'duration': '1/3', 'target': 1}],
            'release': [{'duration': '1/8', 'target': 0}],
        }
    )
    raw = {
        'envelope': definition,
        'bindings': [{'name': 'key', 'kind': 'key'}],
        'modulation': {
            'sources': [
                {'name': 'key', 'scope': 'voice', 'minimum': -200, 'maximum': 10000}
            ],
            'parameters': [
                {
                    'target': {'name': 'envelope', 'parameter': 'on-0-duration'},
                    'unit': 'beats',
                    'scope': 'voice',
                    'minimum': 0,
                    'maximum': 2,
                    'default': 1 / 3,
                }
            ],
            'routes': [
                {
                    'name': 'time',
                    'source': 'key',
                    'target': {'name': 'envelope', 'parameter': 'on-0-duration'},
                    'operation': 'multiply',
                    'unit': 'ratio',
                    'points': [{'input': 60, 'amount': 2}],
                }
            ],
        },
    }
    settings = SoundSettings.model_validate(raw)
    assert settings.envelope.segments[0].duration == Fraction(1, 3)
    assert (
        modulation.evaluate(
            settings.modulation, {'key': modulation.SourceValue(value=60)}
        )[0].value
        == 2 / 3
    )
    raw['bindings'][0] = {'name': 'key', 'kind': 'control', 'control': 'expression'}
    with pytest.raises(ValidationError, match='latched'):
        SoundSettings.model_validate(raw)


def test_spatial_bounds_include_both_scopes_and_delayed_lfo_neutral() -> None:
    raw = body(lfo_settings())
    SampleInstrument.model_validate(raw)
    raw['instrument']['processing'] = {'pan': 0.8}
    with pytest.raises(ValidationError, match='combined pan range'):
        SampleInstrument.model_validate(raw)
    raw = body(lfo_settings())
    raw['slots'][0]['processing'] = {'pan': 0.8}
    raw['slots'][0]['modulation']['parameters'][0]['default'] = 0.8
    raw['slots'][0]['modulation']['routes'][0]['points'] = [
        {'input': 0, 'amount': -0.5}
    ]
    raw['instrument']['processing'] = {'pan': 0.4}
    SampleInstrument.model_validate(raw)
    raw['slots'][0]['lfos']['motion']['delay'] = '1/2'
    with pytest.raises(ValidationError, match='combined pan range'):
        SampleInstrument.model_validate(raw)


@pytest.mark.parametrize('generator', ['envelopes', 'lfos'])
def test_slot_generators_require_voice_scope(generator: str) -> None:
    value = (
        {
            'segments': [{'duration': 0, 'target': 1}],
            'release': [{'duration': 0, 'target': 0}],
        }
        if generator == 'envelopes'
        else {'rate': 1}
    )
    raw = body({generator: {'motion': value | {'scope': 'instrument'}}})
    with pytest.raises(ValidationError, match='voice scope'):
        SampleInstrument.model_validate(raw)


def lfo_settings() -> dict[str, object]:
    return {
        'lfos': {'motion': {'rate': 1}},
        'bindings': [{'name': 'motion', 'kind': 'lfo', 'reference': 'motion'}],
        'modulation': {
            'sources': [
                {'name': 'motion', 'scope': 'voice', 'minimum': -1, 'maximum': 1}
            ],
            'parameters': [
                {
                    'target': {'name': 'processing', 'parameter': 'pan'},
                    'scope': 'voice',
                    'unit': 'normalized',
                    'minimum': -1,
                    'maximum': 1,
                    'default': 0,
                }
            ],
            'routes': [
                {
                    'name': 'pan',
                    'source': 'motion',
                    'target': {'name': 'processing', 'parameter': 'pan'},
                    'operation': 'add',
                    'unit': 'normalized',
                    'points': [
                        {'input': -1, 'amount': -0.5},
                        {'input': 1, 'amount': 0.5},
                    ],
                }
            ],
        },
    }


def body(settings: dict[str, object]) -> dict[str, object]:
    return {
        'instrument': {},
        'slices': [{'name': 'sample', 'asset': 'audio', 'end_frame': 48000}],
        'slots': [
            {
                'name': 'voice',
                'slice': 'sample',
                'mapping': {
                    'lowest_key': 0,
                    'highest_key': 127,
                    'pitch_tracking': False,
                },
                'channels': [{'input': 'mono', 'output': 'mono', 'gain': 1}],
                **settings,
            }
        ],
    }
