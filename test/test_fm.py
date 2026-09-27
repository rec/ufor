import pytest
from pydantic import ValidationError

from ufor import synth_trace
from ufor.codec import parse_score, score_toml
from ufor.events import Release, Trigger
from ufor.fm import FM, FMEdge, Operator
from ufor.synth import FMVoice, SynthInstrument, SynthInstrumentScore


def voice() -> FMVoice:
    return FMVoice.model_validate(
        {
            'name': 'bell',
            'mapping': {'lowest_key': 0, 'highest_key': 127, 'reference_pitch_hz': 440},
            'channels': [{'input': 'mono', 'output': 'mono', 'gain': 1}],
            'fm': {
                'operators': [{'name': 'modulator', 'ratio': 2}, {'name': 'carrier'}],
                'edges': [
                    {'source': 'modulator', 'destination': 'carrier', 'index': 3}
                ],
                'carrier': 'carrier',
            },
            'modulation': {
                'parameters': [
                    {
                        'target': {
                            'name': 'edge-modulator-carrier',
                            'parameter': 'index',
                        },
                        'unit': 'radians',
                        'scope': 'voice',
                        'minimum': 0,
                        'maximum': 8,
                        'default': 3,
                    }
                ]
            },
        }
    )


def test_fm_uses_shared_trigger_and_release_preparation() -> None:
    definition = SynthInstrument(voices=[voice()])
    trace = synth_trace.prepare(
        definition,
        [
            Trigger(
                tick=0, ordinal=0, part='main', trigger_id='a', key=69, pitch_hz=440
            ),
            Release(tick=48000, ordinal=0, part='main', trigger_id='a'),
        ],
        seed=0,
    )
    starts = [a for a in trace.actions if isinstance(a, synth_trace.VoiceStart)]
    assert len(starts) == 1
    assert starts[0].oscillator is None
    assert starts[0].settings == voice()
    assert starts[0].pitch_hz == 440
    assert trace.actions[-1].action == 'release'
    assert synth_trace.SynthTrace.model_validate_json(trace.model_dump_json()) == trace


def test_fm_score_round_trips_through_common_codec() -> None:
    score = SynthInstrumentScore.model_validate(
        {
            'name': 'fm',
            'title': 'FM',
            'timebases': [
                {'name': 'audio', 'kind': 'physical', 'rate': {'numerator': 48000}}
            ],
            'body': {'voices': [voice().model_dump()]},
            'inputs': [
                {
                    'name': 'performance',
                    'stream': {
                        'family': 'event',
                        'timebase': 'audio',
                        'kinds': ['trigger', 'release', 'control_change'],
                    },
                    'binding': {'performance': True},
                }
            ],
            'outputs': [
                {
                    'name': 'audio',
                    'stream': {
                        'family': 'sampled',
                        'quantity': 'audio_amplitude',
                        'unit': 'full_scale',
                        'timebase': 'audio',
                        'channels': ['mono'],
                    },
                    'binding': {'audio': True},
                }
            ],
        }
    )
    assert parse_score(score_toml(score)) == score


@pytest.mark.parametrize('source,destination', [('a', 'missing')])
def test_fm_rejects_invalid_edges(source: str, destination: str) -> None:
    with pytest.raises(ValidationError, match='endpoint'):
        FM(
            operators=[Operator(name='a'), Operator(name='b')],
            carrier='b',
            edges=[FMEdge(source=source, destination=destination)],
        )


def test_fm_accepts_delayed_cycles_and_rejects_current_cycles() -> None:
    operators = [Operator(name=name) for name in ('a', 'b', 'c', 'd')]
    profile = FM(
        operators=operators,
        carrier='d',
        edges=[
            FMEdge(source='a', destination='b', index=1),
            FMEdge(source='b', destination='d', index=1),
            FMEdge(source='d', destination='a', index=1, delayed=True),
        ],
    )
    assert profile.carrier == 'd'
    with pytest.raises(ValidationError, match='acyclic'):
        FM(
            operators=operators,
            carrier='d',
            edges=[
                FMEdge(source='a', destination='b'),
                FMEdge(source='b', destination='a'),
            ],
        )


def test_fm_requires_names_only_for_ambiguous_edge_targets() -> None:
    operators = [Operator(name=name) for name in ('a', 'b', 'c')]
    with pytest.raises(ValidationError, match='edge target'):
        FM(
            operators=operators,
            carrier='c',
            edges=[
                FMEdge(source='a', destination='b'),
                FMEdge(source='a', destination='b', delayed=True),
            ],
        )
    profile = FM(
        operators=operators,
        carrier='c',
        edges=[
            FMEdge(source='a', destination='b'),
            FMEdge(name='feedback', source='a', destination='b', delayed=True),
        ],
    )
    assert profile.edges[1].name == 'feedback'


@pytest.mark.parametrize(
    'parameter,unit,minimum',
    [
        ('index', 'ratio', 0),
        ('index', 'radians', -1),
        ('unknown', 'ratio', 0),
    ],
)
def test_fm_rejects_invalid_parameter_domains(
    parameter: str, unit: str, minimum: float
) -> None:
    raw = voice().model_dump()
    target_name = 'edge-modulator-carrier' if parameter == 'index' else 'fm'
    raw['modulation']['parameters'] = [
        {
            'target': {'name': target_name, 'parameter': parameter},
            'unit': unit,
            'scope': 'voice',
            'minimum': minimum,
            'maximum': 8,
            'default': 0,
        }
    ]
    with pytest.raises(ValidationError):
        FMVoice.model_validate(raw)
