import json
from math import fsum, sqrt
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor import audio_effects, modulation
from ufor.samples.processing import ModulationSettings

DATA = json.loads((Path(__file__).parents[1] / 'conformance/effects.json').read_text())


def test_resonant_delay_exposes_nominal_decay_and_preserves_fixed_tuning() -> None:
    data = json.loads(
        (Path(__file__).parents[1] / 'conformance/resonant-delay.json').read_text()
    )
    graph = audio_effects.EffectGraph.model_validate(data)
    assert graph.output_channels() == ['left', 'right']
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    audio_effects.validate_action(
        graph,
        audio_effects.ParameterAction(
            tick=0,
            ordinal=0,
            processor='string',
            parameter='decay_seconds',
            value='2 s',
            duration_frames=64,
        ),
    )
    for parameter, value in [
        ('frequency_hz', 220),
        ('damping_hz', 3000),
        ('feedback', 0.9),
        ('decay_seconds', 0),
    ]:
        with pytest.raises(ValueError):
            audio_effects.validate_parameter(graph.processors[0], parameter, value)
    with pytest.raises(ValueError, match='state_floor'):
        audio_effects.ResonantDelay(name='string', frequency_hz=440, state_floor=1e-6)


def test_matrix_delay_preserves_layout_and_exposes_shared_delay_controls() -> None:
    data = json.loads(
        (Path(__file__).parents[1] / 'conformance/matrix-delay.json').read_text()
    )
    graph = audio_effects.EffectGraph.model_validate(data)
    assert graph.output_channels() == ['left', 'right']
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    for parameter, value in [
        ('delay_seconds', '20 ms'),
        ('feedback', 0.7),
        ('damping_hz', '2 kHz'),
    ]:
        audio_effects.validate_action(
            graph,
            audio_effects.ParameterAction(
                tick=0, ordinal=0, processor='echo', parameter=parameter, value=value
            ),
        )
    data['inputs'][0]['channels'] = ['mono']
    with pytest.raises(ValueError, match='input channel count'):
        audio_effects.EffectGraph.model_validate(data)


@pytest.mark.parametrize('profile', ['doubling', 'ensemble', 'adt'])
@pytest.mark.parametrize('stereo', [False, True])
def test_modulated_multitap_preserves_authored_voices_and_stereo_routing(
    profile: str, stereo: bool
) -> None:
    data = json.loads(
        (Path(__file__).parents[1] / 'conformance/modulated-multitap.json').read_text()
    )
    recipe = next(p for p in data['profiles'] if p['name'] == profile)
    taps = [audio_effects.ModulatedTap.model_validate(t) for t in recipe['taps']]
    if stereo:
        taps = [
            t.model_copy(
                update={
                    'delay': t.delay.model_copy(
                        update={
                            'channel_phase_offsets': t.delay.channel_phase_offsets * 2
                        }
                    )
                }
            )
            for t in taps
        ]
    graph = audio_effects.modulated_multitap_graph(
        profile,
        audio_effects.AttachmentScope.host,
        audio_effects.GraphInput(
            name='main',
            channels=['left', 'right'] if stereo else ['centre'],
            source=audio_effects.MainStream(),
        ),
        taps,
        256,
        recipe['dry_gain_db'],
        owner='host',
    )
    assert graph.output_channels() == ['left', 'right']
    assert graph.owner == 'host'
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    assert all(n == 0 for n in graph.latencies().values())
    delays = [
        p for p in graph.processors if isinstance(p, audio_effects.ModulatedDelay)
    ]
    assert delays == [
        t.delay.model_copy(update={'name': f'{profile}-tap-{t.delay.name}'})
        for t in taps
    ]
    assert not any(isinstance(p, audio_effects.TapDelay) for p in graph.processors)
    for parameter, value in [
        ('base_delay_seconds', 0.02),
        ('depth_seconds', 0.001),
        ('rate_hz', 0.5),
    ]:
        audio_effects.validate_action(
            graph,
            audio_effects.ParameterAction(
                tick=0,
                ordinal=0,
                processor=f'{profile}-tap-one',
                parameter=parameter,
                value=value,
            ),
        )


def test_modulated_multitap_rejects_empty_and_duplicate_voice_names() -> None:
    source = audio_effects.GraphInput(
        name='main', channels=['mono'], source=audio_effects.MainStream()
    )
    voice = audio_effects.ModulatedTap(
        delay=audio_effects.ModulatedDelay(
            name='one', base_delay_seconds=0.02, maximum_delay_seconds=0.05, rate_hz=0.5
        )
    )
    for taps in [[], [voice, voice]]:
        with pytest.raises(ValueError, match='at least one|duplicate tap name'):
            audio_effects.modulated_multitap_graph(
                'ensemble', audio_effects.AttachmentScope.master, source, taps, 256
            )


@pytest.mark.parametrize(
    'matrix',
    [
        [],
        [[1, 0]],
        [[1.1]],
        [[0.6, -0.5], [0, 0]],
        [[float('nan')]],
        [[1e308, 1e308], [0, 0]],
    ],
)
def test_matrix_delay_rejects_unbounded_or_malformed_feedback(
    matrix: list[list[float]],
) -> None:
    with pytest.raises(ValueError):
        audio_effects.MatrixDelay(
            name='echo',
            delay_seconds=0.01,
            maximum_delay_seconds=0.1,
            feedback_matrix=matrix,
        )


def test_matrix_delay_accepts_signed_contractive_rows_without_normalization() -> None:
    matrix = [[0.25, -0.75], [-1, 0]]
    delay = audio_effects.MatrixDelay(
        name='echo',
        delay_seconds=0.01,
        maximum_delay_seconds=0.1,
        feedback_matrix=matrix,
    )
    assert delay.feedback_matrix == matrix
    with pytest.raises(ValueError, match='feedback'):
        audio_effects.validate_parameter(delay, 'feedback', 1)
    with pytest.raises(ValueError, match='not prepared'):
        audio_effects.validate_parameter(delay, 'damping_hz', 1000)


def test_tap_delay_damping_is_prepared_explicitly_and_accepts_frequency_controls() -> (
    None
):
    data = json.loads(
        (Path(__file__).parents[1] / 'conformance/feedback-damping.json').read_text()
    )
    graph = audio_effects.EffectGraph.model_validate(data)
    processor = graph.processors[0]
    assert isinstance(processor, audio_effects.TapDelay)
    assert processor.damping_hz == 1000
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    action = audio_effects.ParameterAction(
        tick=0,
        ordinal=0,
        processor='echo',
        parameter='damping_hz',
        value='2 kHz',
        duration_frames=64,
    )
    assert action.value == 2000
    audio_effects.validate_action(graph, action)
    with pytest.raises(ValueError, match='must be positive'):
        audio_effects.validate_parameter(processor, 'damping_hz', 0)
    disabled = processor.model_copy(update={'damping_hz': None})
    with pytest.raises(ValueError, match='not prepared'):
        audio_effects.validate_parameter(disabled, 'damping_hz', 2000)


@pytest.mark.parametrize('channels', [['centre'], ['left', 'right']])
def test_multitap_expands_named_taps_into_portable_stereo_routing(
    channels: list[str],
) -> None:
    data = json.loads(
        (Path(__file__).parents[1] / 'conformance/multitap.json').read_text()
    )
    graph = audio_effects.multitap_graph(
        data['name'],
        audio_effects.AttachmentScope.master,
        audio_effects.GraphInput(
            name='main', channels=channels, source=audio_effects.MainStream()
        ),
        [audio_effects.DelayTap.model_validate(t) for t in data['taps']],
        256,
    )
    assert graph.output_channels() == data['channels']
    assert graph.latencies() == data['latencies']
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    processors = {p.name: p for p in graph.processors}
    first = processors['echo-tap-first']
    assert isinstance(first, audio_effects.TapDelay)
    assert (first.delay_seconds, first.maximum_delay_seconds, first.feedback) == (
        0.01,
        0.05,
        0,
    )
    placement = processors['echo-pan-first']
    assert isinstance(placement, audio_effects.ChannelMatrix)
    assert placement.input_channels == channels
    assert placement.coefficients == (
        [[1], [0]] if len(channels) == 1 else [[1, 0], [0, 0]]
    )
    mixer = processors['echo']
    assert isinstance(mixer, audio_effects.Mixer)
    assert [(i.name, i.gain_db) for i in mixer.inputs] == [
        ('dry', 0),
        ('tap-first', -3),
        ('tap-last', -9),
    ]
    for processor, parameter, value in [
        ('echo-tap-first', 'delay_seconds', '30 ms'),
        ('echo', 'tap-first-gain_db', '-6 dB'),
    ]:
        audio_effects.validate_action(
            graph,
            audio_effects.ParameterAction(
                tick=0, ordinal=0, processor=processor, parameter=parameter, value=value
            ),
        )


def test_multitap_requires_unique_bounded_taps_and_a_supported_layout() -> None:
    source = audio_effects.GraphInput(
        name='main', channels=['mono'], source=audio_effects.MainStream()
    )
    tap = audio_effects.DelayTap(
        name='one', delay_seconds=0.01, maximum_delay_seconds=0.02
    )
    with pytest.raises(ValueError, match='at least one tap'):
        audio_effects.multitap_graph(
            'echo', audio_effects.AttachmentScope.master, source, [], 256
        )
    with pytest.raises(ValueError, match='duplicate tap name'):
        audio_effects.multitap_graph(
            'echo', audio_effects.AttachmentScope.master, source, [tap, tap], 256
        )
    with pytest.raises(ValueError, match='mono or named'):
        audio_effects.multitap_graph(
            'echo',
            audio_effects.AttachmentScope.master,
            source.model_copy(update={'channels': ['a', 'b', 'c']}),
            [tap],
            256,
        )
    with pytest.raises(ValidationError, match='prepared maximum'):
        audio_effects.DelayTap(
            name='one', delay_seconds=0.03, maximum_delay_seconds=0.02
        )


@pytest.mark.parametrize('kind', ['gate', 'expander'])
def test_gate_and_expander_have_explicit_detectors_and_no_latency(kind: str) -> None:
    data = json.loads(
        (Path(__file__).parents[1] / 'conformance/gate-expander.json').read_text()
    )
    raw = data['graph']
    if kind == 'expander':
        raw['processors'] = [data['expander']]
    graph = audio_effects.EffectGraph.model_validate(raw)
    processor = graph.processors[0]
    assert audio_effects.processor_ports(processor) == {'input', 'detector'}
    assert graph.output_channels() == data['channels']
    assert graph.latencies() == {'dynamics': data['latency_frames']}
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    action = audio_effects.ParameterAction(
        tick=0,
        ordinal=0,
        processor='dynamics',
        parameter='attack_seconds',
        value='2 ms',
        duration_frames=64,
    )
    assert action.value == 0.002
    audio_effects.validate_action(graph, action)
    with pytest.raises(ValueError, match='nonnegative'):
        audio_effects.validate_parameter(processor, 'release_seconds', -0.1)
    if kind == 'gate':
        action = audio_effects.ParameterAction(
            tick=0,
            ordinal=0,
            processor='dynamics',
            parameter='hysteresis_db',
            value='3 dB',
        )
        audio_effects.validate_action(graph, action)
        action = audio_effects.ParameterAction(
            tick=0,
            ordinal=0,
            processor='dynamics',
            parameter='hold_seconds',
            value='0.5 ms',
        )
        assert action.value == 0.0005
        audio_effects.validate_action(graph, action)
    else:
        audio_effects.validate_parameter(processor, 'ratio', 1)
        with pytest.raises(ValueError, match='at least one'):
            audio_effects.validate_parameter(processor, 'ratio', 0.99)


def test_follower_control_dependencies_order_and_align_audio() -> None:
    data = json.loads(
        (Path(__file__).parents[1] / 'conformance/follower.json').read_text()
    )
    graph = audio_effects.EffectGraph.model_validate(data['graph'])
    assert graph.order() == data['order']
    assert graph.latencies() == data['latencies']
    assert graph.output_channels() == data['channels']
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    audio_effects.validate_action(
        graph,
        audio_effects.ParameterAction(
            tick=0,
            ordinal=0,
            processor='level',
            parameter='attack_seconds',
            value='0 ms',
        ),
    )
    with pytest.raises(ValueError, match='no bypass'):
        audio_effects.validate_action(
            graph,
            audio_effects.BypassAction(
                tick=0, ordinal=0, processor='level', bypassed=True
            ),
        )
    raw = graph.model_dump()
    raw['connections'][1]['source'] = {'kind': 'processor', 'processor': 'output'}
    with pytest.raises(ValidationError, match='cycle'):
        audio_effects.EffectGraph.model_validate(raw)


def test_follower_analysis_is_effect_only_and_cannot_feed_audio() -> None:
    data = json.loads(
        (Path(__file__).parents[1] / 'conformance/follower.json').read_text()
    )
    raw = data['graph']
    with pytest.raises(ValidationError, match='require an effect graph'):
        ModulationSettings.model_validate(
            {n: raw[n] for n in ['bindings', 'modulation']}
        )
    raw['output'] = {'kind': 'processor', 'processor': 'level'}
    with pytest.raises(ValidationError, match='audio output'):
        audio_effects.EffectGraph.model_validate(raw)
    raw['output'] = {'kind': 'processor', 'processor': 'output'}
    raw['connections'][0]['source'] = {'kind': 'processor', 'processor': 'level'}
    with pytest.raises(ValidationError, match='audio port'):
        audio_effects.EffectGraph.model_validate(raw)


def test_follower_binding_requires_a_valid_analysis_source() -> None:
    data = json.loads(
        (Path(__file__).parents[1] / 'conformance/follower.json').read_text()
    )
    raw = data['graph']
    raw['bindings'][0]['processor'] = 'missing'
    with pytest.raises(ValidationError, match='requires a follower processor'):
        audio_effects.EffectGraph.model_validate(raw)
    raw['bindings'][0]['processor'] = 'level'
    raw['modulation']['sources'][0]['minimum'] = -1
    with pytest.raises(ValidationError, match='minimum zero'):
        audio_effects.EffectGraph.model_validate(raw)


def test_mixer_named_ports_selectors_and_gain_units() -> None:
    data = json.loads(
        (Path(__file__).parents[1] / 'conformance/mixer.json').read_text()
    )
    graph = audio_effects.EffectGraph.model_validate(data['graph'])
    processor = graph.processors[0]
    assert isinstance(processor, audio_effects.Mixer)
    assert processor.switch_fade_frames == data['switch_fade_frames']
    assert audio_effects.processor_ports(processor) == {'a', 'b', 'c'}
    assert graph.output_channels() == ['left', 'right']
    action = audio_effects.ParameterAction(
        tick=0,
        ordinal=0,
        processor='sum',
        parameter='b-gain_db',
        value='-3 dB',
        duration_frames=128,
    )
    assert action.value == -3
    audio_effects.validate_action(graph, action)
    selector = audio_effects.ParameterAction(
        tick=0, ordinal=0, processor='sum', parameter='b-solo', value=1
    )
    audio_effects.validate_action(graph, selector)
    with pytest.raises(ValueError, match='immediate requests'):
        audio_effects.validate_action(
            graph, selector.model_copy(update={'duration_frames': 64})
        )
    with pytest.raises(ValueError, match='zero or one'):
        audio_effects.validate_action(graph, selector.model_copy(update={'value': 0.5}))
    with pytest.raises(ValueError, match='no bypass'):
        audio_effects.validate_action(
            graph,
            audio_effects.BypassAction(
                tick=0, ordinal=0, processor='sum', bypassed=True
            ),
        )
    raw = graph.model_dump()
    raw['inputs'][1]['channels'].reverse()
    with pytest.raises(ValidationError, match='matching named layouts'):
        audio_effects.EffectGraph.model_validate(raw)


def test_crossfader_laws_require_an_explicit_choice() -> None:
    for law in ('linear', 'equal_power'):
        processor = audio_effects.Crossfader(name='fade', law=law)
        assert audio_effects.processor_ports(processor) == {'first', 'second'}
        audio_effects.validate_parameter(processor, 'position', 1)
        with pytest.raises(ValueError, match='position'):
            audio_effects.validate_parameter(processor, 'position', 1.1)
    with pytest.raises(ValidationError, match='Field required'):
        audio_effects.Crossfader(name='fade')


def test_channel_matrix_layout_and_always_applied_routing() -> None:
    data = json.loads(
        (Path(__file__).parents[1] / 'conformance/channel-matrix.json').read_text()
    )
    graph = audio_effects.EffectGraph.model_validate(data['graph'])
    assert graph.output_channels() == ['left', 'right', 'mono']
    assert graph.latencies() == {'route': 0}
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    for action in [
        audio_effects.BypassAction(tick=0, ordinal=0, processor='route', bypassed=True),
        audio_effects.ParameterAction(
            tick=0, ordinal=0, processor='route', parameter='mix', value=0
        ),
    ]:
        with pytest.raises(ValueError, match='routing matrices'):
            audio_effects.validate_action(graph, action)
    for vector in data['vectors']:
        result = [
            fsum(a * b for a, b in zip(r, vector['input'], strict=True))
            for r in vector['coefficients']
        ]
        assert result == vector['output']
    with pytest.raises(ValidationError, match='rows/columns'):
        audio_effects.ChannelMatrix(
            name='bad',
            input_channels=['mono'],
            output_channels=['left', 'right'],
            coefficients=[[1]],
        )
    raw = graph.model_dump()
    raw['inputs'][0]['channels'].reverse()
    with pytest.raises(ValidationError, match='layout must match'):
        audio_effects.EffectGraph.model_validate(raw)


def test_static_routing_presets_have_explicit_gain_laws() -> None:
    assert audio_effects.polarity_matrix('flip', ['mono']).coefficients == [[-1]]
    assert audio_effects.pan_matrix('pan', -1).coefficients == [[1], [0]]
    assert audio_effects.pan_matrix('pan', 1).coefficients == [[0], [1]]
    assert [
        r[0] for r in audio_effects.pan_matrix('pan', 0).coefficients
    ] == pytest.approx([1 / sqrt(2), 1 / sqrt(2)])
    assert audio_effects.balance_matrix('balance', 0).coefficients == [[1, 0], [0, 1]]
    assert audio_effects.balance_matrix('balance', 1).coefficients == [[0, 0], [0, 1]]
    assert audio_effects.width_matrix('width', 0).coefficients == [
        [0.5, 0.5],
        [0.5, 0.5],
    ]
    assert audio_effects.width_matrix('width', 2).coefficients == [
        [1.5, -0.5],
        [-0.5, 1.5],
    ]
    encode = audio_effects.mid_side_matrix('encode')
    decode = audio_effects.mid_side_matrix('decode', decode=True)
    assert encode.output_channels == decode.input_channels == ['mid', 'side']
    for i in range(2):
        for j in range(2):
            assert fsum(
                decode.coefficients[i][k] * encode.coefficients[k][j] for k in range(2)
            ) == pytest.approx(float(i == j))
    with pytest.raises(ValueError, match='width'):
        audio_effects.width_matrix('width', 2.1)


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


def test_highpass_units_layout_and_parameter_contract() -> None:
    data = json.loads(
        (Path(__file__).parents[1] / 'conformance/highpass.json').read_text()
    )
    graph = audio_effects.EffectGraph.model_validate(data['graph'])
    assert graph.output_channels() == ['left', 'right']
    assert graph.latencies() == {'dc': data['latency_frames']}
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    action = audio_effects.ParameterAction(
        tick=0, ordinal=0, processor='dc', parameter='cutoff_hz', value='5 Hz'
    )
    audio_effects.validate_action(graph, action)
    assert action.value == 5
    assert audio_effects.Highpass(name='dc').cutoff_hz == 20
    with pytest.raises(ValueError, match='positive'):
        audio_effects.validate_parameter(graph.processors[0], 'cutoff_hz', 0)
    with pytest.raises(ValidationError, match='state_floor'):
        audio_effects.Highpass(name='dc', state_floor=1e-6)


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
