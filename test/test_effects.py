import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor import audio_effects, modulation

DATA = json.loads((Path(__file__).parents[1] / 'conformance/effects.json').read_text())


def test_phaser_sweep_uses_cents_and_bounded_feedback() -> None:
    data = json.loads(
        (Path(__file__).parents[1] / 'conformance/phaser.json').read_text()
    )
    graph = audio_effects.EffectGraph.model_validate(data['graph'])
    processor = graph.processors[0]
    assert isinstance(processor, audio_effects.Phaser)
    assert processor.depth_cents == 2400
    assert graph.latencies()['motion'] == data['latency_frames']
    assert graph.parameter_definition(
        modulation.Target(name='motion', parameter='depth_cents')
    ) == (modulation.Unit.cents, 2400)
    for name, sweep in [('negative', -1), ('zero', 0), ('positive', 1)]:
        assert (
            processor.center_hz * 2 ** (processor.depth_cents * sweep / 1200)
            == data['swept_frequency_hz'][name]
        )
    for parameter, value in [('center_hz', '1 kHz'), ('depth_cents', '1 octave')]:
        action = audio_effects.ParameterAction(
            tick=0, ordinal=0, processor='motion', parameter=parameter, value=value
        )
        audio_effects.validate_action(graph, action)
    for parameter, value in [
        ('center_hz', 0),
        ('depth_cents', -1),
        ('sweep', 1.01),
        ('feedback', 0.951),
        ('feedback', -0.951),
    ]:
        with pytest.raises(ValueError):
            audio_effects.validate_parameter(processor, parameter, value)
    with pytest.raises(ValidationError, match='state_floor'):
        audio_effects.Phaser(name='motion', state_floor=1e-6)
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )


def test_compressor_accepts_independent_detector_layout_and_parameter_units() -> None:
    data = json.loads(
        (Path(__file__).parents[1] / 'conformance/compressor.json').read_text()
    )
    graph = audio_effects.EffectGraph.model_validate(data['graph'])
    assert graph.output_channels() == ['left', 'right']
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    compressor = audio_effects.Compressor.model_validate(
        {'name': 'duck', 'threshold_db': '-12 dB', 'attack_seconds': '10 ms'}
    )
    assert compressor.threshold_db == -12
    assert compressor.attack_seconds == 0.01
    action = audio_effects.ParameterAction.model_validate(
        {
            'tick': 0,
            'ordinal': 0,
            'processor': 'duck',
            'parameter': 'release_seconds',
            'value': '200 ms',
        }
    )
    assert action.value == 0.2
    audio_effects.validate_action(graph, action)
    for parameter, value in (
        ('ratio', 0.5),
        ('knee_db', -1),
        ('attack_seconds', -0.1),
        ('release_seconds', -0.1),
    ):
        with pytest.raises(ValueError):
            audio_effects.validate_action(
                graph,
                action.model_copy(update={'parameter': parameter, 'value': value}),
            )


def test_effect_graph_conformance() -> None:
    graph = audio_effects.EffectGraph.model_validate(DATA['graph'])

    assert graph.order() == DATA['order']
    assert graph.output_channels() == DATA['output_channels']
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )


def test_reverb_declares_stereo_output_and_a_bounded_predelay() -> None:
    data = json.loads(
        (Path(__file__).parents[1] / 'conformance/reverb.json').read_text()
    )
    graph = audio_effects.EffectGraph.model_validate(data['graph'])
    assert graph.output_channels() == data['output_channels']
    assert (
        audio_effects.reverb_delay_frames(data['sample_rate']) == data['delay_frames']
    )
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    room = graph.processors[0]
    for parameter, value in (
        ('predelay_seconds', 0.3),
        ('decay_seconds', 0),
        ('damping_hz', 0),
    ):
        with pytest.raises(ValueError):
            audio_effects.validate_parameter(room, parameter, value)
    for channels in (['left', 'right'], ['mono']):
        raw = graph.model_dump()
        raw['inputs'][0]['channels'] = channels
        assert audio_effects.EffectGraph.model_validate(raw).output_channels() == [
            'left',
            'right',
        ]
    raw['inputs'][0]['channels'] = ['a', 'b']
    with pytest.raises(ValidationError, match='mono or named'):
        audio_effects.EffectGraph.model_validate(raw)
    with pytest.raises(ValidationError, match='prepared maximum'):
        audio_effects.Reverb(
            name='room', predelay_seconds=0.5, maximum_predelay_seconds=0.25
        )
    assert (
        audio_effects.ParameterAction.model_validate(
            {
                'tick': 0,
                'ordinal': 0,
                'processor': 'room',
                'parameter': 'predelay_seconds',
                'value': '20 ms',
            }
        ).value
        == 0.02
    )


def test_tap_retiming_prepares_an_explicit_positive_frame_duration() -> None:
    definition = audio_effects.TapDelay.model_validate(
        {
            'name': 'echo',
            'delay_seconds': '10 ms',
            'maximum_delay_seconds': '1 s',
            'retime_fade_frames': '128 frames',
        }
    )
    assert definition.retime_fade_frames == 128
    with pytest.raises(ValidationError):
        audio_effects.TapDelay(
            name='echo',
            delay_seconds=0.01,
            maximum_delay_seconds=1,
            retime_fade_frames=0,
        )


def test_effect_generators_share_voice_binding_and_route_contracts() -> None:
    value = DATA['graph'] | {
        'envelfos': {'motion': {'kind': 'lfo', 'rate': 1, 'scope': 'voice'}},
        'bindings': [{'name': 'motion', 'kind': 'envelfo', 'reference': 'motion'}],
        'modulation': {
            'sources': [
                {'name': 'motion', 'scope': 'voice', 'minimum': -1, 'maximum': 1}
            ],
            'parameters': [
                {
                    'target': {'name': 'trim', 'parameter': 'gain_db'},
                    'scope': 'voice',
                    'unit': 'db',
                    'default': DATA['graph']['processors'][0]['gain_db'],
                    'minimum': -12,
                    'maximum': 12,
                }
            ],
            'routes': [
                {
                    'name': 'motion',
                    'source': 'motion',
                    'target': {'name': 'trim', 'parameter': 'gain_db'},
                    'unit': 'db',
                    'operation': 'add',
                    'points': [{'input': -1, 'amount': -3}, {'input': 1, 'amount': 3}],
                }
            ],
        },
    }
    graph = audio_effects.EffectGraph.model_validate(value)
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    value['bindings'] = [{'name': 'motion', 'kind': 'envelfo', 'reference': 'missing'}]
    with pytest.raises(ValidationError, match='Unknown local envelfo'):
        audio_effects.EffectGraph.model_validate(value)


def test_effect_action_batch_conformance() -> None:
    graph = audio_effects.EffectGraph.model_validate(DATA['graph'])
    batch = audio_effects.ActionBatch.model_validate(DATA['batch'])

    audio_effects.validate_batch(graph, batch)
    assert not batch.lifecycle
    assert (
        audio_effects.ActionBatch.model_validate_json(batch.model_dump_json()) == batch
    )


def test_graph_rejects_cycle() -> None:
    value = DATA['graph'] | {
        'connections': [
            {
                'processor': 'trim',
                'port': 'input',
                'source': {'kind': 'processor', 'processor': 'ring'},
            },
            *DATA['graph']['connections'][1:],
        ]
    }

    with pytest.raises(ValidationError, match='cycle'):
        audio_effects.EffectGraph.model_validate(value)


def test_graph_rejects_missing_port() -> None:
    value = DATA['graph'] | {'connections': DATA['graph']['connections'][:-1]}

    with pytest.raises(ValidationError, match='unconnected ports'):
        audio_effects.EffectGraph.model_validate(value)


def test_graph_rejects_mismatched_multiply_channels() -> None:
    value = json.loads(json.dumps(DATA['graph']))
    value['inputs'][1]['channels'] = ['mono']

    with pytest.raises(ValidationError, match='matching channel layouts'):
        audio_effects.EffectGraph.model_validate(value)


@pytest.mark.parametrize('case', DATA['grain_windows'])
def test_grain_window_conformance(case: dict[str, object]) -> None:
    assert audio_effects.grain_window(case['index'], case['frames']) == pytest.approx(
        case['value'], abs=1e-15
    )


def test_grain_scheduler_conformance() -> None:
    case = DATA['grain_scheduler']
    phase = 0.0
    launches: list[bool] = []
    for _ in case['launches']:
        launch, phase = audio_effects.grain_launches(
            phase, case['density_hz'], case['sample_rate']
        )
        launches.append(launch)

    assert launches == case['launches']
    assert phase == 0


@pytest.mark.parametrize('case', DATA['grain_jitter'])
def test_grain_jitter_conformance(case: dict[str, object]) -> None:
    assert audio_effects.grain_jitter(case['counter']) == case['value']


def test_parameter_validation() -> None:
    graph = audio_effects.EffectGraph.model_validate(DATA['graph'])
    invalid = audio_effects.ParameterAction(
        tick=0,
        ordinal=0,
        processor='ring',
        parameter='gain_db',
        value=1.0,
    )

    with pytest.raises(ValueError, match='unsupported parameter'):
        audio_effects.validate_action(graph, invalid)


def test_granulator_requires_its_read_history() -> None:
    with pytest.raises(ValidationError, match='history is too short'):
        audio_effects.Granulator(
            name='cloud',
            duration_seconds=0.1,
            density_hz=20.0,
            lookback_seconds=0.2,
            playback_ratio=2.0,
            position_jitter_seconds=0.05,
            history_seconds=0.44,
            maximum_grains=8,
        )


def test_grain_duration_cap_is_explicit_and_bounds_actions_and_routes() -> None:
    example = audio_effects.Granulator.model_validate_json(
        (Path(__file__).parents[1] / 'conformance/grain-cap.json').read_text()
    )
    assert example.maximum_duration_seconds == 0.08
    grain = audio_effects.Granulator(
        name='cloud',
        duration_seconds=0.04,
        density_hz=50,
        playback_ratio=0.25,
        history_seconds=0.02,
        maximum_grains=4,
    )
    assert grain.maximum_duration_seconds == 0.04
    assert grain.model_dump()['maximum_duration_seconds'] == 0.04
    with pytest.raises(ValidationError, match='prepared maximum'):
        audio_effects.Granulator.model_validate(
            grain.model_dump() | {'maximum_duration_seconds': 0.03}
        )
    with pytest.raises(ValueError, match='prepared maximum'):
        audio_effects.validate_parameter(grain, 'duration_seconds', 0.06)
    larger = audio_effects.Granulator.model_validate(
        grain.model_dump() | {'maximum_duration_seconds': '80 ms'}
    )
    audio_effects.validate_parameter(larger, 'duration_seconds', 0.06)
    raw = DATA['graph'] | {
        'processors': [grain.model_dump()],
        'connections': [
            {
                'processor': 'cloud',
                'port': 'input',
                'source': {'kind': 'input', 'input': 'main'},
            }
        ],
        'output': {'kind': 'processor', 'processor': 'cloud'},
        'modulation': {
            'parameters': [
                {
                    'target': {'name': 'cloud', 'parameter': 'duration_seconds'},
                    'scope': 'voice',
                    'unit': 'seconds',
                    'minimum': 0.01,
                    'maximum': 0.06,
                    'default': 0.04,
                }
            ],
        },
    }
    with pytest.raises(ValidationError, match='prepared maximum'):
        audio_effects.EffectGraph.model_validate(raw)
    raw['processors'] = [larger.model_dump()]
    audio_effects.EffectGraph.model_validate(raw)


def test_waveshaper_requires_positive_drive() -> None:
    with pytest.raises(ValidationError, match='greater than 0'):
        audio_effects.Waveshaper(name='clip', drive=0)


def test_waveshaper_profiles_report_aligned_graph_latency() -> None:
    data = json.loads(
        (Path(__file__).parents[1] / 'conformance/waveshaper.json').read_text()
    )
    graph = audio_effects.EffectGraph.model_validate(data['graph'])
    assert graph.latencies() == data['latencies']
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    for parameter, value in [
        ('bias', -0.5),
        ('output_gain_db', '6 dB'),
        ('drive', 4.0),
    ]:
        audio_effects.validate_action(
            graph,
            audio_effects.ParameterAction(
                tick=0,
                ordinal=0,
                processor='clip',
                parameter=parameter,
                value=value,
            ),
        )
    with pytest.raises(ValidationError, match='Input should be'):
        audio_effects.Waveshaper(name='clip', curve='fold')


def test_tap_delay_has_bounded_feedback_and_automation() -> None:
    delay = audio_effects.TapDelay(
        name='echo', delay_seconds=0.125, maximum_delay_seconds=0.5, feedback=0.75
    )

    audio_effects.validate_parameter(delay, 'delay_seconds', 0.5)
    audio_effects.validate_parameter(delay, 'feedback', 0.0)
    with pytest.raises(ValueError, match='prepared maximum'):
        audio_effects.validate_parameter(delay, 'delay_seconds', 0.6)
    with pytest.raises(ValueError, match='feedback'):
        audio_effects.validate_parameter(delay, 'feedback', 1.0)
    with pytest.raises(ValidationError, match='prepared maximum'):
        audio_effects.TapDelay(
            name='echo', delay_seconds=0.6, maximum_delay_seconds=0.5
        )


def test_modulated_delay_bounds_chorus_and_flanger_reads() -> None:
    delay = audio_effects.ModulatedDelay(
        name='movement',
        base_delay_seconds=0.02,
        depth_seconds=0.01,
        maximum_delay_seconds=0.04,
        rate_hz=0.8,
        channel_phase_offsets=[0, 0.5],
    )

    audio_effects.validate_parameter(delay, 'base_delay_seconds', 0.025)
    audio_effects.validate_parameter(delay, 'depth_seconds', 0.015)
    audio_effects.validate_parameter(delay, 'rate_hz', 0)
    with pytest.raises(ValueError, match='positive minimum'):
        audio_effects.ModulatedDelay(
            name='movement',
            base_delay_seconds=0.01,
            depth_seconds=0.01,
            maximum_delay_seconds=0.04,
            rate_hz=0.8,
        )
    with pytest.raises(ValueError, match='prepared maximum'):
        audio_effects.ModulatedDelay(
            name='movement',
            base_delay_seconds=0.03,
            depth_seconds=0.02,
            maximum_delay_seconds=0.04,
            rate_hz=0.8,
        )
