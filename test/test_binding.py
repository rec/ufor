import pytest
from pydantic import ValidationError

from ufor.binding import (
    BindingScore,
    ParameterMapping,
    map_enum_parameter,
    map_parameter,
)
from ufor.codec import parse_score, score_toml
from ufor.modulation import Unit


def mapping(conversion: str = 'log_normalize') -> ParameterMapping:
    return ParameterMapping(
        parameter='cutoff',
        native_id='cutoff',
        unit=Unit.hz,
        conversion=conversion,
        input_min=20,
        input_max=20000,
        output_min=0,
        output_max=1,
    )


def test_logarithmic_mapping_has_a_geometric_midpoint() -> None:
    assert map_parameter(mapping(), 20) == 0
    assert map_parameter(mapping(), 20000) == 1
    assert map_parameter(mapping(), 20 * 1000**0.5) == pytest.approx(0.5)


def test_gain_silence_uses_an_explicit_native_mute() -> None:
    gain = ParameterMapping(
        parameter='gain',
        native_id='level',
        unit=Unit.ratio,
        conversion='gain_db',
        input_min=0,
        input_max=1,
        output_min=-120,
        output_max=0,
    )
    assert map_parameter(gain, 0) is None
    assert map_parameter(gain, 1) == 0


def test_binding_round_trips_and_rejects_ambiguous_native_parameters() -> None:
    score = BindingScore.model_validate(
        {
            'name': 'vl70m',
            'title': 'VL70m SysEx librarian binding',
            'body': {
                'definition': {'path': 'patch.toml'},
                'adapter': 'sysexy.vl70m',
                'implementation': 'yamaha-vl70m',
                'implementation_revision': 'observed-174-byte-bulk',
                'capabilities': [
                    {
                        'name': 'sysex',
                        'live': True,
                        'offline': False,
                        'deterministic': True,
                        'state_restore': True,
                        'latency_ticks': 0,
                    }
                ],
            },
        }
    )
    assert parse_score(score_toml(score)) == score
    data = score.model_dump()
    data['body']['parameters'] = [
        mapping().model_dump(),
        mapping().model_dump() | {'parameter': 'resonance'},
    ]
    with pytest.raises(ValidationError, match='native parameter'):
        BindingScore.model_validate(data)


def test_binding_maps_table_values_and_describes_streams() -> None:
    mapping = ParameterMapping(
        parameter='gobo',
        native_id='wheel',
        unit=Unit.logical,
        conversion='enum_table',
        input_min=0,
        input_max=1,
        output_min=0,
        output_max=1,
        values=[{'input': 'open', 'output': '0'}, {'input': 'dots', 'output': '12'}],
    )
    assert map_enum_parameter(mapping, 'dots') == '12'
    binding = BindingScore.model_validate(
        {
            'name': 'adapter',
            'title': 'Adapter',
            'body': {
                'definition': {'path': 'definition.toml'},
                'adapter': 'example.adapter',
                'implementation': 'example',
                'implementation_revision': '1',
                'capabilities': [
                    {
                        'name': 'render',
                        'live': True,
                        'offline': True,
                        'deterministic': True,
                        'state_restore': True,
                        'latency_ticks': 0,
                    }
                ],
                'streams': [
                    {
                        'name': 'main',
                        'direction': 'output',
                        'family': 'audio',
                        'channels': 2,
                        'rate': 48000,
                    }
                ],
                'channels': [
                    {'logical': 'main', 'native': 'out_1_2', 'direction': 'output'}
                ],
                'parameters': [mapping.model_dump()],
            },
        }
    )
    assert binding.body.channels[0].native == 'out_1_2'
