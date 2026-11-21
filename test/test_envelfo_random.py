import json
from fractions import Fraction
from pathlib import Path

import pytest

from ufor.envelfo import PatchEventConnection
from ufor.envelfo_random import stream_key
from ufor.samples.processing import EnvelfoEventConnection
from ufor.voice_start import prepare_values


def test_envelfo_streams_depend_on_seed_and_identity() -> None:
    assert stream_key(0, 'voice-0') == stream_key(0, 'voice-0')
    assert stream_key(0, 'voice-0') != stream_key(1, 'voice-0')
    assert stream_key(0, 'voice-0') != stream_key(0, 'voice-1')


def test_voice_starts_match_shared_pitch_and_stream_vectors() -> None:
    vectors = json.loads(
        (Path(__file__).parents[1] / 'conformance/voice-start.json').read_text()
    )
    for spec in vectors['starts']:
        expected = spec['expected']
        assert prepare_values(
            spec['seed'],
            spec['voice_id'],
            spec['pitch_hz'],
            spec['frequency_offset_hz'],
            spec['noise'],
        ) == (
            expected['pitch_hz'],
            int(expected['envelfo_key'], 16),
            expected['noise_key'],
        )
    with pytest.raises(ValueError, match='pitch must be finite'):
        prepare_values(0, 'voice-0', 1e308, 1e308, False)
    graph = vectors['graph_stream']
    assert stream_key(graph['seed'], graph['identity']) == int(graph['key'], 16)


@pytest.mark.parametrize('probability', [-0.1, 1.1, float('nan'), float('inf'), True])
def test_event_gate_rejects_invalid_probabilities(probability: float) -> None:
    with pytest.raises(ValueError):
        EnvelfoEventConnection(
            source='clock',
            port='pulse',
            destination='accent',
            cue='hit',
            probability=probability,
        )


@pytest.mark.parametrize('delay', [-1, '-1/64', float('nan'), float('inf'), True])
def test_event_connections_reject_invalid_delays(delay: object) -> None:
    for model, fields in (
        (PatchEventConnection, {'source': 'clock.pulse', 'target': 'accent'}),
        (
            EnvelfoEventConnection,
            {'source': 'clock', 'port': 'pulse', 'destination': 'accent', 'cue': 'hit'},
        ),
    ):
        with pytest.raises(ValueError):
            model.model_validate(fields | {'delay': delay})


def test_event_connection_delays_preserve_exact_seconds() -> None:
    connection = EnvelfoEventConnection(
        source='clock', port='pulse', destination='accent', cue='hit', delay='1/64'
    )
    assert connection.delay == Fraction(1, 64)
    assert (
        EnvelfoEventConnection.model_validate_json(connection.model_dump_json())
        == connection
    )
    assert PatchEventConnection(source='clock.pulse', target='accent').delay == 0
