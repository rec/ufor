from fractions import Fraction
from math import exp, log

import pytest

from ufor.approach import ExponentialApproach
from ufor.envelfo import Envelope
from ufor.envelope import Curve, curve_at
from ufor.modulation import Target, Unit
from ufor.samples.processing import SoundSettings
from ufor.segments import Segment


@pytest.mark.parametrize('seconds', [0, 0.00001, 0.1])
def test_positive_time_floor_preserves_zero_time(seconds: float) -> None:
    stage = ExponentialApproach(
        asymptote=0,
        time_constant=seconds,
        minimum_time_constant=0.001,
        threshold=0.0001,
        transition_to=0,
        transition_seconds=0.05,
    )
    parts = stage.resolve(1)
    if seconds:
        assert float(parts[0].duration) == pytest.approx(
            max(seconds, 0.001) * log(10000), abs=5e-10
        )
    else:
        assert parts == [Segment(duration=Fraction(1, 20), to=0)]
    settings = SoundSettings(
        envelope=Envelope(
            initial=1,
            segments=[Segment(duration=0, to=1)],
            release=[stage],
        )
    )
    assert settings.parameter_definition(
        Target(name='envelope', parameter='release-0-time_constant')
    ) == (Unit.seconds, seconds)


@pytest.mark.parametrize('initial', [1.0, 0.1, 0.0001, 0.00001, 0.0])
def test_release_resolves_from_captured_level(initial: float) -> None:
    stage = ExponentialApproach(
        asymptote=0.0,
        time_constant=1 / 9,
        threshold=0.0001,
        transition_to=0.0,
        transition_seconds=0.05,
        minimum_transition_distance=0.0001,
    )
    parts = stage.resolve(initial)
    assert float(parts[-1].duration) == pytest.approx(
        0.05 * min(1, initial / 0.0001), abs=5e-10
    )
    if initial > 0.0001:
        assert float(parts[0].duration) == pytest.approx(
            log(initial / 0.0001) / 9, abs=5e-10
        )
        assert curve_at(
            Curve(initial=initial, segments=parts), parts[0].duration / 2
        ) == pytest.approx(initial * exp(parts[0].curve / 2))
    else:
        assert len(parts) == 1


def test_approach_roundtrips_without_becoming_a_fixed_segment() -> None:
    body = Envelope(
        initial=1.0,
        segments=[
            ExponentialApproach(
                asymptote=0.0,
                time_constant='1 s',
                threshold=0.1,
                transition_to=0.0,
                transition_seconds='50 ms',
            )
        ],
    )
    assert Envelope.model_validate_json(body.model_dump_json()) == body
    with pytest.raises(ValueError, match='one-shot'):
        Envelope.model_validate(body.model_dump() | {'playback': 'loop'})


def test_zero_time_preserves_captured_value_for_terminal_fade() -> None:
    stage = ExponentialApproach(
        asymptote=0.0,
        time_constant=0.0,
        threshold=0.0001,
        transition_to=0.0,
        transition_seconds=0.05,
    )
    assert stage.resolve(0.5) == [Segment(duration=Fraction(1, 20), to=0.0)]
