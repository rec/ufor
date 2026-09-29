import pytest
from pydantic import TypeAdapter, ValidationError

from ufor.codec import parse_score, score_toml
from ufor.events import LFOChange, MidiEvent, OscEvent, OscMessage, StoredEvent
from ufor.interface import EventType, Output, SequenceBinding
from ufor.sequence import EventSequence, SequenceScore
from ufor.time import Rate, Timebase


def test_raw_events_preserve_timestamp_order_and_payload() -> None:
    event = MidiEvent(tick=-1, ordinal=2, data=[144, 60, 100])
    adapter = TypeAdapter(StoredEvent)
    assert adapter.validate_json(adapter.dump_json(event)) == event


def test_packet_validation_rejects_invalid_storage() -> None:
    with pytest.raises(ValidationError, match='bytes'):
        MidiEvent(tick=0, ordinal=0, data=[256])
    with pytest.raises(ValidationError, match='base64'):
        OscEvent(tick=0, ordinal=0, direction='in', data_b64='!')


def test_toml_rejects_null_osc_arguments_without_dropping_positions() -> None:
    score = SequenceScore(
        name='osc',
        title='OSC',
        timebases=[Timebase(name='ticks', rate=Rate(numerator=1))],
        body=EventSequence(
            timebase='ticks',
            end=1,
            events=[
                OscEvent(
                    tick=0,
                    ordinal=0,
                    direction='in',
                    data_b64='',
                    decoded=[OscMessage(path='/test', types=',iNi', args=[1, None, 2])],
                ),
            ],
        ),
    )
    assert SequenceScore.model_validate_json(score.model_dump_json()) == score
    with pytest.raises(ValueError, match='TOML cannot represent null array arguments'):
        score_toml(score)


def test_lfo_change_sequence_declares_and_round_trips_its_output() -> None:
    score = SequenceScore(
        name='lfo',
        title='LFO change',
        timebases=[Timebase(name='ticks', rate=Rate(numerator=48000))],
        outputs=[
            Output(
                name='events',
                stream=EventType(timebase='ticks', kinds=['lfo_change']),
                binding=SequenceBinding(),
            )
        ],
        body=EventSequence(
            timebase='ticks',
            end=48000,
            events=[
                LFOChange(tick=0, ordinal=0, name='vibrato', action='rate', rate=5.0)
            ],
        ),
    )
    assert SequenceScore.model_validate_json(score.model_dump_json()) == score
    assert parse_score(score_toml(score)) == score
