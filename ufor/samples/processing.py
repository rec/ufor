"""Sample processing declarations bound to the shared control and route models."""

from fractions import Fraction
from math import cos, pi, sin
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .. import control, modulation
from ..base import FiniteScalar, Frequency, Identifier, Model, Positive, unique
from ..envelope import Envelope
from ..lfo import LFO
from ..modulation import Modulation, Target, Unit
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


class GeneratorBinding(Model):
    name: Identifier
    kind: Literal['envelope', 'lfo']
    reference: Identifier


Binding = Annotated[
    EventBinding | ControlBinding | GeneratorBinding, Field(discriminator='kind')
]


class SoundSettings(Model):
    processing: Processing = Processing()
    envelope: Envelope | None = None
    envelopes: dict[Identifier, Envelope] = Field(default_factory=dict)
    lfos: dict[Identifier, LFO] = Field(default_factory=dict)
    modulation: Modulation = Modulation()
    bindings: list[Binding] = Field(default_factory=list)

    @model_validator(mode='after')
    def local_references(self) -> Self:
        unique([*self.envelopes, *self.lfos], 'source ID')
        unique((b.name for b in self.bindings), 'binding ID')
        sources = {s.name: s for s in self.modulation.sources}
        if sources.keys() != {b.name for b in self.bindings}:
            raise ValueError('Each modulation source requires exactly one binding')
        if self.envelope is not None and (
            self.envelope.scope != control.Scope.voice
            or self.envelope.polarity != control.Polarity.unipolar
        ):
            raise ValueError('Amplitude envelope must be unipolar and voice scoped')
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
                generators = self.envelopes if binding.kind == 'envelope' else self.lfos
                if binding.reference not in generators:
                    raise ValueError(
                        f'Unknown local {binding.kind} source: {binding.reference}'
                    )
                generator = generators[binding.reference]
                minimum = (
                    0
                    if isinstance(generator, Envelope)
                    and generator.polarity == control.Polarity.unipolar
                    else -1
                )
                if (source.scope, source.minimum, source.maximum) != (
                    generator.scope,
                    minimum,
                    1,
                ):
                    raise ValueError(
                        'Generator source scope and domain must match its definition'
                    )
        for parameter in self.modulation.parameters:
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
            elif parameter.target.name.startswith('env-'):
                generator = self.envelopes.get(
                    parameter.target.name.removeprefix('env-')
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
            if route.target.name == 'envelope' or route.target.name.startswith('env-'):
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
    generators = {f'env-{k}': v for k, v in settings.envelopes.items()}
    if settings.envelope is not None:
        generators['envelope'] = settings.envelope
    if target.name in generators:
        definition = generators[target.name]
        for phase, segments in (
            ('on', definition.segments),
            ('release', definition.release),
        ):
            for index, segment in enumerate(segments):
                if target.parameter == f'{phase}-{index}-duration':
                    unit = (
                        modulation.Unit.seconds
                        if definition.clock == control.Clock.seconds
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
        and b.kind == 'lfo'
        and (settings.lfos[b.reference].delay or settings.lfos[b.reference].fade_in)
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
