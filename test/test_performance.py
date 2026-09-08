import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from ufor import events
from ufor.codec import document_toml, parse_document
from ufor.sequence import SequenceDocument


@pytest.mark.parametrize('key', [-500, 128, 10000])
def test_triggers_keep_selection_pitch_and_expression_independent(key: int) -> None:
    trigger = events.Trigger(
        tick=48001,
        ordinal=0,
        part='percussion',
        trigger_id='hit-1',
        key=key,
        velocity=0.5000001,
        pitch_hz=443.123456,
        controls={'pressure': 0.123456789},
    )
    restored = TypeAdapter(events.PerformanceEvent).validate_json(
        trigger.model_dump_json()
    )
    assert restored == trigger
    assert trigger.key == key
    assert trigger.pitch_hz == 443.123456
    assert trigger.velocity == 0.5000001
    assert trigger.controls['pressure'] == 0.123456789
    with pytest.raises(ValidationError, match='frozen'):
        trigger.key = 60


def test_zero_velocity_is_a_trigger_and_release_addresses_its_identity() -> None:
    adapter = TypeAdapter(events.PerformanceEvent)
    first = adapter.validate_python(
        {
            'kind': 'trigger',
            'tick': 0,
            'ordinal': 0,
            'part': 'pads',
            'trigger_id': 'first',
            'key': 42,
            'velocity': 0.0,
        }
    )
    second = events.Trigger(tick=1, ordinal=1, part='pads', trigger_id='second', key=42)
    release = events.Release(tick=2, ordinal=2, part='pads', trigger_id='first')
    assert isinstance(first, events.Trigger)
    assert first.pitch_hz is None
    assert first.trigger_id != second.trigger_id
    assert release.trigger_id == first.trigger_id
    assert adapter.validate_json(release.model_dump_json()) == release


@pytest.mark.parametrize(
    'target',
    [
        {'scope': 'instrument'},
        {'scope': 'part', 'part': 'keyboard'},
        {'scope': 'trigger', 'part': 'keyboard', 'trigger_id': 'held-1'},
    ],
)
def test_control_targets_roundtrip(target: dict[str, object]) -> None:
    event = events.ControlChange.model_validate(
        {
            'tick': 120,
            'ordinal': 0,
            'control': 'bend',
            'value': -0.123456789,
            **target,
        }
    )
    assert (
        TypeAdapter(events.PerformanceEvent).validate_json(event.model_dump_json())
        == event
    )
    assert event.value == -0.123456789


@pytest.mark.parametrize(
    'target',
    [
        {'scope': 'instrument', 'part': 'keyboard'},
        {'scope': 'instrument', 'trigger_id': 'held-1'},
        {'scope': 'part'},
        {'scope': 'part', 'part': 'keyboard', 'trigger_id': 'held-1'},
        {'scope': 'trigger', 'part': 'keyboard'},
        {'scope': 'trigger', 'trigger_id': 'held-1'},
        {'scope': 'voice'},
        {'scope': 'channel', 'part': 'keyboard'},
    ],
)
def test_control_changes_require_unambiguous_targets(target: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        events.ControlChange.model_validate(
            {
                'tick': 0,
                'ordinal': 0,
                'control': 'bend',
                'value': 0.0,
                **target,
            }
        )


@pytest.mark.parametrize(
    'changes',
    [
        {'ordinal': -1},
        {'ordinal': True},
        {'tick': 0.5},
        {'tick': True},
        {'frame': 0},
        {'key': 60.5},
        {'key': True},
        {'velocity': -0.001},
        {'velocity': 1.001},
        {'velocity': float('nan')},
        {'velocity': True},
        {'pitch_hz': 0},
        {'pitch_hz': float('inf')},
        {'controls': {'pressure': 1.01}},
        {'controls': {'pressure': float('nan')}},
        {'channel': 1},
        {'note': 60},
    ],
)
def test_invalid_trigger_values_are_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        events.Trigger.model_validate(
            {
                'tick': 0,
                'ordinal': 0,
                'part': 'keys',
                'trigger_id': 'hit',
                'key': 60,
                **changes,
            }
        )


def test_performance_sequences_preserve_preroll_and_equal_time_order() -> None:
    sequence = SequenceDocument.model_validate(
        json.loads(
            (Path(__file__).parents[1] / 'conformance/performance.json').read_text()
        )
    )
    assert parse_document(document_toml(sequence)) == sequence
    adapter = TypeAdapter(events.StoredEvent)
    assert [
        adapter.validate_json(e.model_dump_json()) for e in sequence.body.events
    ] == sequence.body.events
