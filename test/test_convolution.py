import json
from pathlib import Path

import pytest

from ufor import audio_effects


def definition() -> dict[str, object]:
    return json.loads(
        (Path(__file__).parents[1] / 'conformance/convolution.json').read_text()
    )


def test_convolution_preserves_explicit_matrix_assets_and_partition_latency() -> None:
    graph = audio_effects.EffectGraph.model_validate(definition())
    assert graph.output_channels() == ['left', 'right']
    assert graph.latencies() == {'room': 256}
    assert graph.assets[0].audio.channels == ['ll', 'lr', 'rl', 'rr']
    assert (graph.timebases[0].rate.numerator, graph.timebases[0].rate.denominator) == (
        48000,
        1,
    )
    assert (
        audio_effects.EffectGraph.model_validate_json(graph.model_dump_json()) == graph
    )
    processor = graph.processors[0]
    assert isinstance(processor, audio_effects.Convolution)
    assert [
        (k.input_channel, k.output_channel, k.channel) for k in processor.kernels
    ] == [
        ('left', 'left', 'll'),
        ('left', 'right', 'lr'),
        ('right', 'left', 'rl'),
        ('right', 'right', 'rr'),
    ]


def test_convolution_latency_composes_with_oversampling_and_dry_routing() -> None:
    raw = definition()
    raw['processors'].extend(
        [
            {'kind': 'gain', 'name': 'dry'},
            {'kind': 'waveshaper', 'name': 'shape'},
            {
                'kind': 'mixer',
                'name': 'mix',
                'inputs': [{'name': 'dry'}, {'name': 'wet'}],
            },
        ]
    )
    raw['connections'].extend(
        [
            {
                'processor': 'dry',
                'port': 'input',
                'source': {'kind': 'input', 'input': 'main'},
            },
            {
                'processor': 'shape',
                'port': 'input',
                'source': {'kind': 'processor', 'processor': 'room'},
            },
            {
                'processor': 'mix',
                'port': 'dry',
                'source': {'kind': 'processor', 'processor': 'dry'},
            },
            {
                'processor': 'mix',
                'port': 'wet',
                'source': {'kind': 'processor', 'processor': 'shape'},
            },
        ]
    )
    raw['output'] = {'kind': 'processor', 'processor': 'mix'}
    graph = audio_effects.EffectGraph.model_validate(raw)
    assert graph.latencies() == {'dry': 0, 'room': 256, 'shape': 304, 'mix': 304}


@pytest.mark.parametrize('partition', [0, 3, 255, -1, True])
def test_convolution_rejects_non_power_of_two_partitions(partition: int) -> None:
    raw = definition()
    raw['processors'][0]['partition_frames'] = partition
    with pytest.raises(ValueError):
        audio_effects.EffectGraph.model_validate(raw)


@pytest.mark.parametrize(
    'problem',
    [
        'asset',
        'channel',
        'input',
        'output',
        'timebase',
        'empty',
        'duplicate_pair',
        'duplicate_asset',
        'duplicate_clock',
        'source_layout',
        'stream',
    ],
)
def test_convolution_requires_consistent_finite_assets_and_named_paths(
    problem: str,
) -> None:
    raw = definition()
    kernel = raw['processors'][0]['kernels'][0]
    asset = raw['assets'][0]
    if problem in {'asset', 'channel'}:
        kernel[problem] = 'missing'
    elif problem in {'input', 'output'}:
        kernel[f'{problem}_channel'] = 'missing'
    elif problem == 'timebase':
        asset['audio']['timebase'] = 'missing'
    elif problem == 'empty':
        asset['audio']['frames'] = 0
    elif problem == 'duplicate_pair':
        raw['processors'][0]['kernels'].append(dict(kernel))
    elif problem == 'duplicate_asset':
        raw['assets'].append(dict(asset))
    elif problem == 'duplicate_clock':
        raw['timebases'].append(dict(raw['timebases'][0]))
    elif problem == 'source_layout':
        raw['inputs'][0]['channels'].reverse()
    else:
        asset['location'] = {
            'kind': 'stream',
            'url': 'https://example.invalid/ir',
            'transport': 'http',
        }
        asset.pop('content')
    with pytest.raises(ValueError):
        audio_effects.EffectGraph.model_validate(raw)


@pytest.mark.parametrize('kind', ['parameter', 'bypass', 'freeze'])
def test_convolution_mix_and_bypass_belong_to_routing_nodes(kind: str) -> None:
    graph = audio_effects.EffectGraph.model_validate(definition())
    if kind == 'parameter':
        action = audio_effects.ParameterAction(
            tick=0, ordinal=0, processor='room', parameter='mix', value=0.5
        )
    elif kind == 'bypass':
        action = audio_effects.BypassAction(
            tick=0, ordinal=0, processor='room', bypassed=True
        )
    else:
        action = audio_effects.FreezeAction(
            tick=0, ordinal=0, processor='room', frozen=True
        )
    with pytest.raises(ValueError, match='always wet'):
        audio_effects.validate_action(graph, action)
