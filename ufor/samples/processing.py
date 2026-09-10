"""Sample processing declarations bound to the shared control and route models."""

from fractions import Fraction
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .. import control, modulation
from ..base import Frequency, Identifier, Model, Number, Positive, unique
from ..envelope import Envelope
from ..lfo import LFO
from ..modulation import Modulation
from .controls import Control


class EqualizerBand(Model):
    name: Identifier
    frequency_hz: Frequency
    gain_db: Number
    resonance: Positive


class Processing(Model):
    volume_db: Number = 0.0
    tuning_cents: Number = 0.0
    pan: Number = 0.0
    stereo_balance: Number = 0.0
    equalizer: list[EqualizerBand] = Field(default_factory=list)

    @model_validator(mode='after')
    def unique_bands(self) -> Self:
        unique((b.name for b in self.equalizer), 'EQ band ID')
        return self


class ChannelRoute(Model):
    input: str = Field(min_length=1)
    output: str = Field(min_length=1)
    gain: Number


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
                    raise ValueError('Key and velocity bindings require voice scope')
                if binding.kind == 'key':
                    if any(v != int(v) for v in (source.minimum, source.maximum)):
                        raise ValueError('Key source bounds must be integers')
                    if any(
                        p.input != int(p.input)
                        for r in self.modulation.routes
                        if r.source == source.name
                        for p in r.points
                    ):
                        raise ValueError('Key mapping inputs must be integers')
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
            unit, default = parameter_definition(self, parameter.target)
            if parameter.unit != unit or parameter.default != default:
                raise ValueError(
                    'Parameter unit and default must match the bound setting'
                )
            if parameter.target.parameter == 'amplitude' and parameter.minimum < 0:
                raise ValueError('Amplitude requires a nonnegative parameter domain')
            if parameter.target.parameter == 'resonance' and parameter.minimum <= 0:
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

    def validate_controls(self, controls: dict[str, Control]) -> None:
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
                        'Control source must match its declared domain '
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
