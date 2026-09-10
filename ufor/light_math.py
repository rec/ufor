"""Small language-neutral light composition reference calculations, without I/O."""

from fractions import Fraction
from math import isfinite

from . import light_animation
from .base import Model
from .interface import OutputSelection
from .lights import Layout, LightType, Wiring


def validate_frame(frame: list[list[float]], count: int, components: int) -> None:
    if count <= 0 or components <= 0:
        raise ValueError('light and component counts must be positive')
    if len(frame) != count or any(len(r) != components for r in frame):
        raise ValueError('frame shape must match light and component counts')
    if any(not isfinite(v) for r in frame for v in r):
        raise ValueError('light values must be finite')


def wire_frame(
    frame: list[list[float]], layout: Layout, wiring: Wiring
) -> list[list[float]]:
    if not frame or not frame[0]:
        raise ValueError('frame must contain light components')
    validate_frame(frame, len(layout.lights), len(frame[0]))
    return [list(frame[i]) for i in wiring.indexes(layout)]


def byte_frame(frame: list[list[float]]) -> list[list[int]]:
    if not frame or not frame[0]:
        raise ValueError('frame must contain light components')
    validate_frame(frame, len(frame), len(frame[0]))
    return [[round(min(1, max(0, v)) * 255) for v in r] for r in frame]


def compose_frame(
    operation: Model,
    output: LightType,
    frames: dict[OutputSelection, list[list[float]]],
    at: Fraction = Fraction(0),
) -> list[list[float]]:
    """Combine already evaluated children in logical order; never advance state."""
    if at < 0:
        raise ValueError('light time must not be negative')
    count, components = len(output.layout.lights), len(output.components)
    requested = (
        [s for s, _, _ in light_animation.cue_weights(operation, at)]
        if isinstance(operation, light_animation.Cues)
        else light_animation.sources(operation)
    )
    for source in requested:
        frame = frames[source]
        size = count
        channels = components
        if isinstance(operation, light_animation.Place):
            size = next(
                len(p.lights) for p in operation.placements if p.source == source
            )
        elif isinstance(operation, light_animation.ComponentMap):
            channels = len(operation.matrix[0])
        validate_frame(frame, size, channels)
    if isinstance(operation, light_animation.Fill):
        result = [list(operation.values) for _ in range(count)]
    elif isinstance(operation, light_animation.Reverse):
        result = [list(r) for r in reversed(frames[operation.source])]
    elif isinstance(operation, light_animation.Gain):
        result = [[v * operation.amount for v in r] for r in frames[operation.source]]
    elif isinstance(operation, light_animation.ComponentMap):
        result = [
            [sum(a * b for a, b in zip(r, m, strict=True)) for m in operation.matrix]
            for r in frames[operation.source]
        ]
    elif isinstance(operation, light_animation.Place):
        result = [[0.0] * components for _ in range(count)]
        indexes = {p.name: i for i, p in enumerate(output.layout.lights)}
        for placement in operation.placements:
            for name, row in zip(
                placement.lights, frames[placement.source], strict=True
            ):
                result[indexes[name]] = list(row)
    elif isinstance(
        operation,
        (light_animation.Mix, light_animation.Crossfade, light_animation.Cues),
    ):
        if isinstance(operation, light_animation.Mix):
            weights = [(s.source, s.weight) for s in operation.sources]
        elif isinstance(operation, light_animation.Crossfade):
            progress = operation.fade.progress(at)
            weights = [
                (operation.outgoing, 1 - progress),
                (operation.incoming, progress),
            ]
        else:
            weights = [(s, w) for s, _, w in light_animation.cue_weights(operation, at)]
        result = [
            [sum(frames[s][i][j] * w for s, w in weights) for j in range(components)]
            for i in range(count)
        ]
        if isinstance(operation, light_animation.Mix):
            result = [[min(1, max(0, v)) for v in r] for r in result]
    else:
        raise ValueError('effect generation requires a host implementation')
    validate_frame(result, count, components)
    return result
