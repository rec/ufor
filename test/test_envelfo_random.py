from fractions import Fraction

import pytest

from ufor.envelfo import PatchEventConnection
from ufor.envelfo_random import stream_key
from ufor.samples.processing import EnvelfoEventConnection


def test_envelfo_streams_depend_on_seed_and_identity() -> None:
    assert stream_key(0, 'voice-0') == stream_key(0, 'voice-0')
    assert stream_key(0, 'voice-0') != stream_key(1, 'voice-0')
    assert stream_key(0, 'voice-0') != stream_key(0, 'voice-1')


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
