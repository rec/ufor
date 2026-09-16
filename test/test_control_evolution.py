import json
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from ufor import control
from ufor.base import Model
from ufor.samples import controls, playback


class Observation(Model):
    at: control.Rational
    value: float


class SmoothingCase(Model):
    name: str
    declaration: controls.ControlDeclaration
    start: control.Rational
    smoothing: control.Rational
    initial: float | None = None
    events: list[controls.ControlValueEvent]
    observations: list[Observation]


def check_smoothing(case: SmoothingCase, restore: bool) -> None:
    state = controls.initial_control(
        case.declaration, case.start, case.smoothing, case.initial
    )
    remaining = iter(case.events)
    event = next(remaining, None)
    for observation in case.observations:
        while event is not None and event.at <= observation.at:
            if restore:
                controls.control_at(state, (state.at + event.at) / 2)
                state = controls.ControlState.model_validate_json(
                    state.model_dump_json()
                )
            state = controls.control_event(case.declaration, state, event)
            event = next(remaining, None)
        if restore:
            controls.control_at(state, (state.at + observation.at) / 2)
            state = controls.ControlState.model_validate_json(state.model_dump_json())
        assert controls.control_at(state, observation.at) == pytest.approx(
            observation.value, abs=DATA['absolute_tolerance'], rel=0
        )


def test_control_events_are_ordered_and_queries_do_not_advance_state() -> None:
    declaration = controls.ControlDeclaration()
    state = controls.initial_control(declaration, Fraction(0), Fraction(1))
    change = controls.ControlValueEvent(at=1, ordinal=2, value=1)
    state = controls.control_event(declaration, state, change)
    for event in [change, controls.ControlValueEvent(at=0, ordinal=3, value=0)]:
        with pytest.raises(ValueError, match='order'):
            controls.control_event(declaration, state, event)
    with pytest.raises(ValueError, match='replay'):
        controls.control_at(state, Fraction(0))
    assert controls.control_at(state, Fraction(3)) == 1
    assert controls.control_at(state, Fraction(3, 2)) == 0.5


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf')])
def test_unipolar_controls_reject_invalid_initial_values_and_targets(
    value: float,
) -> None:
    declaration = controls.ControlDeclaration()
    with pytest.raises(ValueError):
        controls.initial_control(declaration, Fraction(0), Fraction(1), value)
    state = controls.initial_control(declaration, Fraction(0), Fraction(1))
    with pytest.raises(ValueError):
        controls.control_event(
            declaration, state, controls.ControlValueEvent(at=0, ordinal=0, value=value)
        )


def test_negative_smoothing_is_rejected() -> None:
    with pytest.raises(ValidationError):
        controls.initial_control(
            controls.ControlDeclaration(), Fraction(0), Fraction(-1)
        )


def test_pitch_tracking_requires_resolved_pitch() -> None:
    mapping = playback.Mapping(lowest_key=0, highest_key=127, reference_pitch_hz=440)
    with pytest.raises(ValueError, match='resolved pitch_hz'):
        playback.pitch_ratio(mapping, None, 0)


DATA = json.loads(
    (Path(__file__).parents[1] / 'conformance/control-evolution.json').read_text()
)
CASES = [SmoothingCase.model_validate(c) for c in DATA['smoothing']]


@pytest.mark.parametrize('case', CASES, ids=lambda c: c.name)
@pytest.mark.parametrize('restore', [False, True])
def test_smoothing_conformance(case: SmoothingCase, restore: bool) -> None:
    check_smoothing(case, restore)


@pytest.mark.parametrize('case', DATA['pitch']['sample'])
def test_sample_pitch_composition(case: dict[str, object]) -> None:
    mapping = playback.Mapping.model_validate(
        {
            'lowest_key': 0,
            'highest_key': 127,
            'pitch_tracking': case['tracking'],
            'reference_pitch_hz': case.get('reference_hz'),
        }
    )
    assert playback.pitch_ratio(
        mapping,
        case['onset_hz'],
        case['instrument_cents'] + case['slot_cents'],
        case['variation_cents'],
    ) == pytest.approx(case['ratio'], abs=DATA['absolute_tolerance'], rel=0)
