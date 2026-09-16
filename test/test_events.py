import pytest
from pydantic import TypeAdapter, ValidationError

from ufor.codec import score_toml
from ufor.events import MidiEvent, OscEvent, OscMessage, StoredEvent
from ufor.sequence import Sequence, SequenceScore
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
        body=Sequence(
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
