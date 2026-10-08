"""Sample processing declarations bound to the shared control and route models."""

from enum import StrEnum, auto
from fractions import Fraction
from math import cos, pi, sin
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from .. import control, modulation
from ..base import (
    FiniteScalar,
    Frequency,
    Identifier,
    Model,
    Positive,
    UnitInterval,
    unique,
)
from ..envelope import Envelope
from ..lfo import Reset
from ..modulation import Modulation, Target, Unit
from ..motion import (
    Affine,
    Contour,
    Cycle,
    MotionUse,
    Patch,
    Product,
    Stages,
    Sum,
    stage_event_ports,
)
from . import enums
from .controls import ControlDeclaration


class EqualizerBand(Model):
    name: Identifier
    frequency_hz: Frequency
    gain_db: FiniteScalar
    resonance: Positive


class FilterResponse(enums.StrEnum):
    lowpass = 'lowpass'
    highpass = 'highpass'
    bandpass = 'bandpass'
    notch = 'notch'


class FilterBoundary(enums.StrEnum):
    error = 'error'
    clamp = 'clamp'


class FilterTolerance(Model):
    coefficient: Positive = 1e-12
    response_db: Positive = 1e-6


class ResonantFilter(Model):
    name: Identifier
    response: FilterResponse
    cutoff_hz: Frequency
    q: Positive = 1 / 2**0.5
    stages: Literal[1, 2] = 1
    boundary: FilterBoundary = FilterBoundary.error
    minimum_hz: Frequency = 1.0
    nyquist_ratio: float = Field(default=0.999, strict=True, gt=0, lt=1)
    tolerance: FilterTolerance = FilterTolerance()


class BiquadCoefficients(Model):
    b0: FiniteScalar
    b1: FiniteScalar
    b2: FiniteScalar
    a1: FiniteScalar
    a2: FiniteScalar


class Processing(Model):
    volume_db: FiniteScalar = 0.0
    invert_polarity: StrictBool = False
    tuning_cents: FiniteScalar = 0.0
    pan: FiniteScalar = 0.0
    stereo_balance: FiniteScalar = 0.0
    equalizer: list[EqualizerBand] = Field(default_factory=list)
    filters: list[ResonantFilter] = Field(default_factory=list)

    @model_validator(mode='after')
    def unique_bands(self) -> Self:
        unique((b.name for b in self.equalizer), 'EQ band ID')
        unique((f.name for f in self.filters), 'filter ID')
        return self


def biquad_coefficients(filter: ResonantFilter, rate_hz: float) -> BiquadCoefficients:
    """Return one RBJ Audio EQ Cookbook biquad at the resolved cutoff."""
    if rate_hz <= 0:
        raise ValueError('filter rate_hz must be positive')
    nyquist = rate_hz / 2
    upper = nyquist * filter.nyquist_ratio
    if filter.minimum_hz >= upper:
        raise ValueError('filter minimum_hz must be below the configured Nyquist bound')
    cutoff = filter.cutoff_hz
    if not filter.minimum_hz <= cutoff <= upper:
        if filter.boundary == FilterBoundary.error:
            raise ValueError('filter cutoff is outside its configured rate bounds')
        cutoff = min(max(cutoff, filter.minimum_hz), upper)
    omega = 2 * pi * cutoff / rate_hz
    alpha = sin(omega) / (2 * filter.q)
    cosine = cos(omega)
    if filter.response == FilterResponse.lowpass:
        b0, b1, b2 = (1 - cosine) / 2, 1 - cosine, (1 - cosine) / 2
    elif filter.response == FilterResponse.highpass:
        b0, b1, b2 = (1 + cosine) / 2, -(1 + cosine), (1 + cosine) / 2
    elif filter.response == FilterResponse.bandpass:
        b0, b1, b2 = alpha, 0.0, -alpha
    else:
        b0, b1, b2 = 1.0, -2 * cosine, 1.0
    a0, a1, a2 = 1 + alpha, -2 * cosine, 1 - alpha
    return BiquadCoefficients(
        b0=b0 / a0,
        b1=b1 / a0,
        b2=b2 / a0,
        a1=a1 / a0,
        a2=a2 / a0,
    )


class ChannelRoute(Model):
    input: str = Field(min_length=1)
    output: str = Field(min_length=1)
    gain: FiniteScalar


class EventBinding(Model):
    name: Identifier
    kind: Literal['key', 'velocity']


class ControlBinding(Model):
    name: Identifier
    kind: Literal['control'] = 'control'
    control: Identifier
    smoothing: control.Rational = Field(default=Fraction(1, 200), ge=0)


class ReleaseTiming(StrEnum):
    event = auto()
    voice = auto()


class GeneratorBinding(Model):
    name: Identifier
    kind: Literal['motion'] = 'motion'
    reference: Identifier
    output: Identifier | None = None
    release_timing: ReleaseTiming = ReleaseTiming.event


class MotionEventConnection(Model):
    source: Identifier
    port: str = Field(min_length=1)
    destination: Identifier
    cue: Identifier
    every: int = Field(default=1, ge=1, strict=True)
    offset: int = Field(default=0, ge=0, strict=True)
    probability: UnitInterval = 1.0
    delay: control.Rational = Field(default=Fraction(0), ge=0)


Binding = Annotated[
    EventBinding | ControlBinding | GeneratorBinding, Field(discriminator='kind')
]


class SoundSettings(Model):
    processing: Processing = Processing()
    envelope: Envelope | None = None
    motions: dict[Identifier, MotionUse] = Field(default_factory=dict)
    modulation: Modulation = Modulation()
    bindings: list[Binding] = Field(default_factory=list)
    event_connections: list[MotionEventConnection] = Field(default_factory=list)

    @model_validator(mode='after')
    def local_references(self) -> Self:
        unique((b.name for b in self.bindings), 'binding ID')
        sources = {s.name: s for s in self.modulation.sources}
        if sources.keys() != {b.name for b in self.bindings}:
            raise ValueError('Each modulation source requires exactly one binding')
        bindings = {b.name: b for b in self.bindings}
        for connection in self.event_connections:
            source = bindings.get(connection.source)
            destination = bindings.get(connection.destination)
            if not isinstance(source, GeneratorBinding) or not isinstance(
                destination, GeneratorBinding
            ):
                raise ValueError('Motion event connections require Motion bindings')
            origin = self.motions.get(source.reference)
            target = self.motions.get(destination.reference)
            if origin is None or target is None:
                raise ValueError('Motion event connection references an unknown Motion')
            if (
                origin.scope != control.Scope.voice
                or target.scope != control.Scope.voice
            ):
                raise ValueError('Motion event connections require voice scope')
            if origin.body is not None:
                if isinstance(origin.body, Patch):
                    ports = origin.body.event_outputs.keys()
                elif isinstance(origin.body, Stages):
                    ports = stage_event_ports(origin.body)
                elif isinstance(origin.body, Cycle):
                    if (
                        origin.clock != control.Clock.seconds
                        or origin.body.rate == 0
                        or origin.body.reset != Reset.trigger
                        or origin.body.delay
                        or origin.body.fade_in
                    ):
                        raise ValueError(
                            'Cycle event source requires a simple seconds clock'
                        )
                    ports = {marker.name for marker in origin.body.markers}
                else:
                    raise ValueError('Motion event source has no event ports')
                if connection.port not in ports:
                    raise ValueError(
                        'Motion event connection references an unknown port'
                    )
            if target.body is not None and (
                not isinstance(target.body, Stages)
                or not any(
                    t.event == f'cue.{connection.cue}' for t in target.body.transitions
                )
            ):
                raise ValueError('Motion event destination has no matching cue')
        if self.envelope is not None and (
            self.envelope.scope != control.Scope.voice
            or self.envelope.polarity != control.Polarity.unipolar
        ):
            raise ValueError('Amplitude envelope must be unipolar and voice scoped')
        patch_release_timings: dict[tuple[str, str], ReleaseTiming] = {}
        for binding in self.bindings:
            source = sources[binding.name]
            if isinstance(binding, EventBinding):
                if source.scope != 'voice':
                    raise ValueError(
                        'NoteKey and velocity bindings require voice scope'
                    )
                if binding.kind == 'key':
                    if any(v != int(v) for v in (source.minimum, source.maximum)):
                        raise ValueError('NoteKey source bounds must be integers')
                    if any(
                        p.input != int(p.input)
                        for r in self.modulation.routes
                        if r.source == source.name
                        for p in r.points
                    ):
                        raise ValueError('NoteKey mapping inputs must be integers')
                elif (source.minimum, source.maximum) != (0, 1):
                    raise ValueError('Velocity source domain must be [0, 1]')
            elif isinstance(binding, GeneratorBinding):
                if binding.reference not in self.motions:
                    raise ValueError(
                        f'Unknown local motion source: {binding.reference}'
                    )
                generator = self.motions[binding.reference]
                if isinstance(generator.body, Patch):
                    if (
                        binding.output is None
                        or binding.output not in generator.body.outputs
                    ):
                        raise ValueError('Patch binding requires a named output')
                    selected = generator.body.motions[
                        generator.body.outputs[binding.output]
                    ]
                    child = (binding.reference, generator.body.outputs[binding.output])
                    if (
                        child in patch_release_timings
                        and patch_release_timings[child] != binding.release_timing
                    ):
                        raise ValueError(
                            'Patch child outputs require one release timing'
                        )
                    patch_release_timings[child] = binding.release_timing
                else:
                    if binding.output is not None and generator.score is None:
                        raise ValueError('Only Patch bindings select named outputs')
                    selected = generator.body
                if (
                    binding.release_timing == ReleaseTiming.voice
                    and generator.body is not None
                    and (not isinstance(selected, Contour) or not selected.release)
                ):
                    raise ValueError(
                        'Voice release timing requires a releasing contour'
                    )
                if generator.score is not None:
                    if source.scope != generator.scope:
                        raise ValueError('Motion source scope must match its use')
                    continue
                minimum = (
                    0
                    if isinstance(selected, Contour)
                    and selected.polarity == control.Polarity.unipolar
                    else -1
                )
                if isinstance(generator.body, Patch) and isinstance(
                    selected, (Sum, Product, Affine)
                ):
                    assert binding.output is not None
                    minimum, maximum = generator.body.signal_ranges[
                        generator.body.outputs[binding.output]
                    ]
                    if (
                        source.scope != generator.scope
                        or source.minimum > minimum
                        or source.maximum < maximum
                    ):
                        raise ValueError(
                            'Patch output range exceeds its declared source domain'
                        )
                    continue
                if (source.scope, source.minimum, source.maximum) != (
                    generator.scope,
                    minimum,
                    1,
                ):
                    raise ValueError(
                        'Generator source scope and domain must match its definition'
                    )
        for parameter in self.modulation.parameters:
            motion = self.motions.get(parameter.target.name.removeprefix('motion-'))
            if parameter.target.name.startswith('motion-') and (
                motion is not None and motion.score is not None
            ):
                if parameter.scope != motion.scope:
                    raise ValueError('Motion parameter scope must match its use')
                continue
            unit, default = self.parameter_definition(parameter.target)
            if parameter.unit != unit or parameter.default != default:
                raise ValueError(
                    'Parameter unit and default must match the bound setting'
                )
            if parameter.target.parameter == 'amplitude' and parameter.minimum < 0:
                raise ValueError('Amplitude requires a nonnegative parameter domain')
            if (
                parameter.target.parameter in ('resonance', 'q')
                and parameter.minimum <= 0
            ):
                raise ValueError('Resonance requires a positive parameter domain')
            if parameter.target.name == 'envelope':
                generator = self.envelope
            elif parameter.target.name.startswith('motion-'):
                motion = self.motions.get(parameter.target.name.removeprefix('motion-'))
                generator = (
                    motion if motion and isinstance(motion.body, Contour) else None
                )
            else:
                generator = None
            if generator is not None and parameter.scope != generator.scope:
                raise ValueError('Envelope parameter scope must match its definition')
        for route in self.modulation.routes:
            if route.operation == modulation.Operation.multiply and any(
                p.amount < 0 for p in route.points
            ):
                raise ValueError('Sample processing multipliers must be nonnegative')
            if route.target.name == 'envelope' or route.target.name.startswith(
                'motion-'
            ):
                binding = next(b for b in self.bindings if b.name == route.source)
                if not isinstance(binding, EventBinding):
                    raise ValueError(
                        'Envelope durations are latched from key or velocity'
                    )
        return self

    def parameter_definition(self, target: Target) -> tuple[Unit, float]:
        """Resolve processing targets with source-specific extension support."""
        return parameter_definition(self, target)

    def validate_controls(self, controls: dict[str, ControlDeclaration]) -> None:
        sources = {s.name: s for s in self.modulation.sources}
        for binding in self.bindings:
            if isinstance(binding, ControlBinding):
                if binding.control not in controls:
                    raise ValueError(f'Unknown control: {binding.control}')
                declared = controls[binding.control]
                source = sources[binding.name]
                minimum = -1 if declared.polarity == control.Polarity.bipolar else 0
                if source.scope == 'voice' or (source.minimum, source.maximum) != (
                    minimum,
                    1,
                ):
                    raise ValueError(
                        'ControlDeclaration source must match its declared domain '
                        'and control scope'
                    )


def parameter_definition(
    settings: SoundSettings, target: modulation.Target
) -> tuple[modulation.Unit, float]:
    """Resolve native parameter addresses without a second route vocabulary."""
    if target.name == 'processing':
        if target.parameter == 'amplitude':
            return modulation.Unit.ratio, 1.0
        units = {
            'volume_db': modulation.Unit.db,
            'tuning_cents': modulation.Unit.cents,
            'pan': modulation.Unit.normalized,
            'stereo_balance': modulation.Unit.normalized,
        }
        if target.parameter in units:
            return units[target.parameter], getattr(
                settings.processing, target.parameter
            )
    for band in settings.processing.equalizer:
        if target.name == f'eq-{band.name}':
            units = {
                'gain_db': modulation.Unit.db,
                'frequency_hz': modulation.Unit.hz,
                'resonance': modulation.Unit.ratio,
            }
            if target.parameter in units:
                return units[target.parameter], getattr(band, target.parameter)
    for filter in settings.processing.filters:
        if target.name == f'filter-{filter.name}':
            units = {'cutoff_hz': modulation.Unit.hz, 'q': modulation.Unit.ratio}
            if target.parameter in units:
                return units[target.parameter], getattr(filter, target.parameter)
    definition: Envelope | Contour | None = None
    clock: control.Clock | None = None
    if target.name == 'envelope' and settings.envelope is not None:
        definition = settings.envelope
        clock = definition.clock
    elif target.name.startswith('motion-'):
        motion = settings.motions.get(target.name.removeprefix('motion-'))
        if motion is not None and isinstance(motion.body, Contour):
            definition = motion.body
            clock = motion.clock
    if definition is not None:
        for phase, segments in (
            ('on', definition.segments),
            ('release', definition.release),
        ):
            for index, segment in enumerate(segments):
                if target.parameter == f'{phase}-{index}-duration':
                    unit = (
                        modulation.Unit.seconds
                        if clock == control.Clock.seconds
                        else modulation.Unit.beats
                    )
                    return unit, float(segment.duration)
    raise ValueError(f'Unknown local parameter: {target.name}.{target.parameter}')


def spatial_bounds(settings: SoundSettings, target: str) -> tuple[float, float]:
    """Conservative route bounds include the neutral contribution during activation."""
    low = high = getattr(settings.processing, target)
    multipliers: list[tuple[float, float]] = []
    weighted = {
        b.name
        for b in settings.bindings
        if isinstance(b, GeneratorBinding)
        and isinstance(body := settings.motions[b.reference].body, Cycle)
        and (body.delay or body.fade_in)
    }
    for route in settings.modulation.routes:
        if route.target == modulation.Target(name='processing', parameter=target):
            amounts = [p.amount for p in route.points]
            if route.source in weighted:
                amounts.append(0 if route.operation == modulation.Operation.add else 1)
            if route.operation == modulation.Operation.add:
                low += min(amounts)
                high += max(amounts)
            else:
                multipliers.append((min(amounts), max(amounts)))
    for minimum, maximum in multipliers:
        values = [low * minimum, low * maximum, high * minimum, high * maximum]
        low, high = min(values), max(values)
    return low, high
