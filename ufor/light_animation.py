"""Component-independent light scores and exact composition semantics."""

from fractions import Fraction
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from . import effects, modulation
from .base import Identifier, Model, unique
from .control import Rational, Scope
from .envelope import Curve, curve_at
from .interface import InterfaceScore, LightBinding, OutputSelection, Part
from .lfo import LFO, initial_lfo, lfo_at
from .lights import Interpretation, LightType
from .modulation import Modulation


class Fill(Model):
    effect: Literal['fill'] = 'fill'
    values: list[float] = Field(min_length=1)


class WeightedSource(Model):
    source: OutputSelection
    weight: float = Field(default=1, ge=0)


class Mix(Model):
    effect: Literal['mix'] = 'mix'
    sources: list[WeightedSource] = Field(min_length=1)


class Placement(Model):
    source: OutputSelection
    lights: list[Identifier] = Field(min_length=1)


class Place(Model):
    effect: Literal['place'] = 'place'
    placements: list[Placement] = Field(min_length=1)

    @model_validator(mode='after')
    def disjoint(self) -> Self:
        unique((n for p in self.placements for n in p.lights), 'placed light')
        return self


class Reverse(Model):
    effect: Literal['reverse'] = 'reverse'
    source: OutputSelection


class Fade(Model):
    duration: Rational = Field(gt=0)
    easing: Literal['linear', 'smooth'] = 'linear'

    def progress(self, at: Fraction) -> float:
        progress = float(min(Fraction(1), max(Fraction(0), at / self.duration)))
        return (
            progress
            if self.easing == 'linear'
            else progress * progress * (3 - 2 * progress)
        )


class Crossfade(Model):
    effect: Literal['crossfade'] = 'crossfade'
    outgoing: OutputSelection
    incoming: OutputSelection
    fade: Fade


class Gain(Model):
    effect: Literal['gain'] = 'gain'
    source: OutputSelection
    amount: float = 1


class Cue(Model):
    source: OutputSelection
    start: Rational = Field(ge=0)
    duration: Rational = Field(gt=0)


class Cues(Model):
    effect: Literal['cues'] = 'cues'
    cues: list[Cue] = Field(min_length=1)
    easing: Literal['linear', 'smooth'] = 'linear'

    @model_validator(mode='after')
    def ordered(self) -> Self:
        # Each cue owns a part; a repeated score is instantiated as another part.
        unique((c.source.name for c in self.cues), 'cue part')
        for i, (left, right) in enumerate(zip(self.cues, self.cues[1:], strict=False)):
            if (
                left.start >= right.start
                or left.start + left.duration >= right.start + right.duration
            ):
                raise ValueError('cues require increasing starts and ends')
            if i and self.cues[i - 1].start + self.cues[i - 1].duration > right.start:
                raise ValueError('at most two cues may overlap')
        return self


class ComponentMap(Model):
    """Explicit output-component rows by input-component columns; no clipping."""

    effect: Literal['component_map'] = 'component_map'
    source: OutputSelection
    matrix: list[list[float]] = Field(min_length=1)

    @model_validator(mode='after')
    def rectangular(self) -> Self:
        if not self.matrix[0] or any(
            len(r) != len(self.matrix[0]) for r in self.matrix
        ):
            raise ValueError('component matrix must be nonempty and rectangular')
        return self


class Control(Model):
    """A free-running control in seconds from this score's activation."""

    name: Identifier
    curve: Curve | LFO

    @model_validator(mode='after')
    def autonomous(self) -> Self:
        if isinstance(self.curve, LFO) and (
            self.curve.clock.value != 'seconds'
            or self.curve.scope != Scope.part
            or self.curve.reset.value != 'free'
        ):
            raise ValueError('light LFO requires seconds, part scope and free reset')
        return self


class Animation(Model):
    operation: Annotated[
        effects.EffectValue
        | Fill
        | Mix
        | Place
        | Reverse
        | Crossfade
        | Gain
        | Cues
        | ComponentMap,
        Field(discriminator='effect'),
    ]
    parts: list[Part] = Field(default_factory=list)
    modulation: Modulation = Field(default_factory=Modulation)
    controls: list[Control] = Field(default_factory=list)

    @model_validator(mode='after')
    def references(self) -> Self:
        unique((p.name for p in self.parts), 'part name')
        names = {p.name for p in self.parts}
        if 'animation' in names:
            raise ValueError('animation is reserved for local parameter targets')
        if any(s.name not in names for s in sources(self.operation)):
            raise ValueError('operation selects an unknown part')
        unique((c.name for c in self.controls), 'control name')
        if {c.name for c in self.controls} != {s.name for s in self.modulation.sources}:
            raise ValueError('each modulation source requires one control')
        if any(s.scope != 'part' for s in self.modulation.sources):
            raise ValueError('animation control sources require part scope')
        for parameter in self.modulation.parameters:
            if parameter.scope != Scope.part:
                raise ValueError('animation parameters require part scope')
            if parameter.target.name != 'animation':
                raise ValueError('local parameter target name must be animation')
            value = getattr(self.operation, parameter.target.parameter, None)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError('parameter must select a numeric operation field')
            for bound in (parameter.minimum, parameter.default, parameter.maximum):
                configured_operation(
                    self.operation, {parameter.target.parameter: bound}
                )
        return self


class AnimationScore(InterfaceScore):
    kind: Literal['animation'] = 'animation'
    body: Animation

    @model_validator(mode='after')
    def light_interface(self) -> Self:
        if self.inputs or len(self.outputs) != 1 or len(self.timebases) != 1:
            raise ValueError(
                'animation requires one output, one clock and no external inputs'
            )
        output = self.outputs[0]
        if not isinstance(output.stream, LightType) or not isinstance(
            output.binding, LightBinding
        ):
            raise ValueError('animation output requires a LightType and LightBinding')
        operation = self.body.operation
        stream = output.stream
        if isinstance(operation, effects.Effect) and (
            stream.components != ['red', 'green', 'blue']
            or stream.interpretation != Interpretation.drive
        ):
            raise ValueError('Lyte RGB effects require red, green, blue drive values')
        if isinstance(operation, Fill) and len(operation.values) != len(
            stream.components
        ):
            raise ValueError('fill values must match output components')
        if isinstance(operation, Place):
            names = {p.name for p in stream.layout.lights}
            if any(n not in names for p in operation.placements for n in p.lights):
                raise ValueError('placement names an unknown output light')
        if isinstance(operation, ComponentMap) and len(operation.matrix) != len(
            stream.components
        ):
            raise ValueError('matrix rows must match output components')
        clock = self.timebases[0].rate
        rate = Fraction(clock.numerator, clock.denominator)
        times = []
        if isinstance(operation, Crossfade):
            times.append(operation.fade.duration)
        if isinstance(operation, Cues):
            times.extend(t for c in operation.cues for t in [c.start, c.duration])
        if any((t * rate).denominator != 1 for t in times):
            raise ValueError('cue and fade boundaries must be exact logical ticks')
        local = {p.target for p in self.body.modulation.parameters}
        names = {p.name for p in self.body.parts}
        if any(
            p.binding not in local and p.binding.name not in names
            for p in self.parameters
        ):
            raise ValueError('export requires a local parameter or named part')
        return self


def sources(operation: object) -> list[OutputSelection]:
    if isinstance(operation, Mix):
        return [s.source for s in operation.sources]
    if isinstance(operation, Place):
        return [p.source for p in operation.placements]
    if isinstance(operation, Crossfade):
        return [operation.outgoing, operation.incoming]
    if isinstance(operation, Cues):
        return [c.source for c in operation.cues]
    if isinstance(operation, (Reverse, Gain, ComponentMap)):
        return [operation.source]
    return []


def configured_operation(operation: Model, parameters: dict[str, float]) -> Model:
    return type(operation).model_validate(operation.model_dump() | parameters)


def control_value(control: Control, at: Fraction) -> modulation.SourceValue:
    if isinstance(control.curve, Curve):
        return modulation.SourceValue(value=curve_at(control.curve, at))
    value = lfo_at(control.curve, initial_lfo(control.curve, Fraction(0)), at)
    return modulation.SourceValue(value=value.value, weight=value.weight)


def operation_at(
    animation: Animation, at: Fraction, parameters: dict[str, float] | None = None
) -> Model:
    """Evaluate controls with the shared modulation rules, then validate settings."""
    base = [
        modulation.ParameterValue(
            target=modulation.Target(name='animation', parameter=k), value=v
        )
        for k, v in (parameters or {}).items()
    ]
    values = modulation.evaluate(
        animation.modulation,
        {c.name: control_value(c, at) for c in animation.controls},
        base,
    )
    return configured_operation(
        animation.operation, {v.target.parameter: v.value for v in values}
    )


def validate_sources(
    score: AnimationScore, selected: dict[OutputSelection, LightType]
) -> None:
    output = score.outputs[0].stream
    assert isinstance(output, LightType)
    operation = score.body.operation
    for source in sources(operation):
        stream = selected[source]
        if stream.interpretation != output.interpretation:
            raise ValueError('light interpretations require an explicit conversion')
        if isinstance(operation, ComponentMap):
            if len(operation.matrix[0]) != len(stream.components):
                raise ValueError('matrix columns must match source components')
        elif stream.components != output.components:
            raise ValueError('light components require an explicit component map')
        if isinstance(operation, Place):
            for placement in operation.placements:
                if placement.source == source and len(placement.lights) != len(
                    stream.layout.lights
                ):
                    raise ValueError(
                        'placement must name one output light per source light'
                    )
        elif stream.layout != output.layout:
            raise ValueError('light layouts must match; use placement to remap lights')


def cue_weights(
    cues: Cues, at: Fraction
) -> list[tuple[OutputSelection, Fraction, float]]:
    """Selected outputs, their cue-local seconds, and their blend weights."""
    active = [c for c in cues.cues if c.start <= at < c.start + c.duration]
    if len(active) < 2:
        return [(c.source, at - c.start, 1.0) for c in active]
    first, second = active
    progress = Fade(
        duration=first.start + first.duration - second.start, easing=cues.easing
    ).progress(at - second.start)
    return [
        (first.source, at - first.start, 1 - progress),
        (second.source, at - second.start, progress),
    ]
