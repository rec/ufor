import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor import synth_trace
from ufor.events import Release, Trigger
from ufor.noise import stream_key
from ufor.synth import NoiseVoice, SynthInstrument


def voice() -> NoiseVoice:
    return NoiseVoice.model_validate(
        {
            'name': 'wind',
            'noise': 'white',
            'mapping': {'lowest_key': 0, 'highest_key': 127, 'pitch_tracking': False},
            'channels': [{'input': 'mono', 'output': 'mono', 'gain': 1}],
        }
    )


def test_noise_stream_keys_match_portable_vectors() -> None:
    vectors = json.loads(
        (Path(__file__).parents[1] / 'conformance/noise-v1.json').read_text()
    )
    for v in vectors['keys']:
        assert stream_key(v['seed'], v['voice_id']) == v['key']
    for s in [-1, 2**64, True]:
        with pytest.raises(ValueError, match='64-bit'):
            stream_key(s, 'voice-0')


def test_noise_preparation_preserves_stream_identity_through_json() -> None:
    definition = SynthInstrument(voices=[voice()])
    events = [
        Trigger(tick=i, ordinal=0, part='main', trigger_id=f'n{i}', key=60)
        for i in (0, 1)
    ]
    events.append(Release(tick=48000, ordinal=0, part='main', trigger_id='n0'))
    trace = synth_trace.prepare(definition, events, seed=0)
    starts = [a for a in trace.actions if isinstance(a, synth_trace.VoiceStart)]
    assert [a.noise_key for a in starts] == [
        stream_key(0, 'voice-0'),
        stream_key(0, 'voice-1'),
    ]
    assert starts[0].noise_key != starts[1].noise_key
    assert trace == synth_trace.prepare(definition, events, seed=0)
    assert synth_trace.SynthTrace.model_validate_json(trace.model_dump_json()) == trace
    assert trace.actions[-1].action == 'release'
    with pytest.raises(ValidationError, match='stream key'):
        synth_trace.VoiceStart.model_validate(
            starts[0].model_dump() | {'noise_key': None}
        )


@pytest.mark.parametrize(
    'change',
    [
        {'noise': 'pink'},
        {'frequency_offset_hz': 1},
        {'processing': {'tuning_cents': 1}},
        {'mapping': {'lowest_key': 0, 'highest_key': 127, 'reference_pitch_hz': 440}},
        {
            'modulation': {
                'parameters': [
                    {
                        'target': {'name': 'processing', 'parameter': 'tuning_cents'},
                        'unit': 'cents',
                        'scope': 'voice',
                        'minimum': 0,
                        'maximum': 1200,
                        'default': 0,
                    }
                ]
            }
        },
    ],
)
def test_noise_rejects_unsupported_source_settings(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        NoiseVoice.model_validate(voice().model_dump() | change)


def test_noise_score_round_trips_through_codec() -> None:
    from ufor.codec import parse_score, score_toml
    from ufor.synth import SynthInstrumentScore

    raw = json.loads(Path('conformance/synth-instrument.json').read_text())
    raw['body']['voices'] = [voice().model_dump(mode='json')]
    raw['body']['voices'][0]['channels'][0]['output'] = raw['outputs'][0]['stream'][
        'channels'
    ][0]
    document = SynthInstrumentScore.model_validate(raw)
    assert parse_score(score_toml(document)) == document
