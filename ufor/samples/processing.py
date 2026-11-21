"""Sample processing declarations bound to the shared control and route models."""

from enum import StrEnum, auto
from fractions import Fraction
from math import cos, pi, sin
from typing import Annotated, ClassVar, Literal, Self

import pydantic
from pydantic import Field, StrictBool, model_validator
from reccy.configuration import units

from .. import control, envelfo, envelfo_contract, modulation, modulation_contract
from ..approach import ExponentialApproach
from ..base import (
    FiniteScalar,
    Frequency,
    Identifier,
    Model,
    Positive,
    UnitInterval,
    unique,
)
from ..envelfo import (
    LFO,
    Affine,
    Envelope,
    Generator,
    Latch,
    Patch,
    Product,
    Quantize,
    Slew,
    Stages,
    Sum,
    Threshold,
    stage_event_ports,
)
from ..lfo import Reset
from ..modulation import Modulation, Target, Unit
from ..segments import Segment
from . import enums
from .controls import ControlDeclaration

_PORTABLE_IDENTIFIER = pydantic.TypeAdapter(modulation_contract.Identifier)


class _ProcessingDeclaration(Model):
    _quantity_fields: ClassVar[dict[str, str]] = {}
    _numeric_fields: ClassVar[tuple[str, ...]] = ()

    @model_validator(mode='wrap')
    @classmethod
    def portable_declaration(
        cls,
        value: object,
        handler: pydantic.ModelWrapValidatorHandler[Self],
        info: pydantic.ValidationInfo,
    ) -> Self:
        if not (info.context and info.context.get('portable')):
            return handler(value)
        if isinstance(value, Model):
            data = envelfo_contract.definition_data(value)
            if 'tolerance' in data and envelfo_contract.omits_default_record(
                value, 'tolerance'
            ):
                data.pop('tolerance')
            value = data
        if not isinstance(value, dict):
            return handler(value)
        data = dict(value)
        if 'name' in data:
            _PORTABLE_IDENTIFIER.validate_python(data['name'], context=info.context)
        for field, unit in cls._quantity_fields.items():
            if field in data:
                data[field] = modulation_contract.scalar_quantity(data[field], unit)
        for field in cls._numeric_fields:
            if field in data:
                data[field] = modulation_contract.scalar(data[field], info)
        if 'stages' in data and type(data['stages']) is not int:
            raise ValueError('Portable filter stages must be integers')
        return handler(data)


class EqualizerBand(_ProcessingDeclaration):
    name: Identifier
    frequency_hz: Frequency
    gain_db: Annotated[FiniteScalar, units.unit_validator('decibel')]
    resonance: Positive
    _quantity_fields = {'frequency_hz': 'hz', 'gain_db': 'db'}
    _numeric_fields = ('resonance',)


class FilterResponse(enums.StrEnum):
    lowpass = 'lowpass'
    highpass = 'highpass'
    bandpass = 'bandpass'
    notch = 'notch'


class FilterBoundary(enums.StrEnum):
    error = 'error'
    clamp = 'clamp'


class FilterOrder(StrEnum):
    before_amplitude = auto()
    after_amplitude = auto()


class PanLaw(StrEnum):
    native = auto()
    sfizz = auto()


class FilterTolerance(_ProcessingDeclaration):
    coefficient: Positive = 1e-12
    response_db: Annotated[Positive, units.unit_validator('decibel')] = 1e-6
    _quantity_fields = {'response_db': 'db'}
    _numeric_fields = ('coefficient',)


class ResonantFilter(_ProcessingDeclaration):
    name: Identifier
    response: FilterResponse
    cutoff_hz: Frequency
    q: Positive = 1 / 2**0.5
    stages: Literal[1, 2] = 1
    boundary: FilterBoundary = FilterBoundary.error
    minimum_hz: Frequency = 1.0
    nyquist_ratio: float = Field(default=0.999, strict=True, gt=0, lt=1)
    tolerance: FilterTolerance = FilterTolerance()
    _quantity_fields = {'cutoff_hz': 'hz', 'minimum_hz': 'hz'}
    _numeric_fields = ('q', 'nyquist_ratio')


class BiquadCoefficients(Model):
    b0: FiniteScalar
    b1: FiniteScalar
    b2: FiniteScalar
    a1: FiniteScalar
    a2: FiniteScalar


class Processing(_ProcessingDeclaration):
    volume_db: Annotated[FiniteScalar, units.unit_validator('decibel')] = 0.0
    invert_polarity: StrictBool = False
    tuning_cents: Annotated[FiniteScalar, units.unit_validator('musical_cent')] = 0.0
    pan: FiniteScalar = 0.0
    stereo_balance: FiniteScalar = 0.0
    equalizer: list[EqualizerBand] = Field(default_factory=list)
    filters: list[ResonantFilter] = Field(default_factory=list)
    filter_order: FilterOrder = FilterOrder.before_amplitude
    _quantity_fields = {'volume_db': 'db', 'tuning_cents': 'cents'}
    _numeric_fields = ('pan', 'stereo_balance')

    @model_validator(mode='after')
    def unique_bands(self) -> Self:
        unique((b.name for b in self.equalizer), 'EQ band ID')
        unique((f.name for f in self.filters), 'filter ID')
        return self


def pan_gains(position: float, law: PanLaw, *, stereo: bool) -> list[float]:
    """Return absolute stereo output gains for mono pan or stereo balance."""
    if not -1 <= position <= 1:
        raise ValueError('pan position must be between -1 and 1')
    if stereo and law == PanLaw.native:
        return [1 - max(position, 0), 1 + min(position, 0)]
    angle = (position + 1) * pi / 4
    gains = [
        0.0 if position == 1 else cos(angle),
        0.0 if position == -1 else sin(angle),
    ]
    if law == PanLaw.sfizz:
        compensation = 10 ** (6 / 20) / 2**0.5 if stereo else 10 ** (3 / 20)
        gains = [g * compensation for g in gains]
    return gains


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


def portable_smoothing(value: object, info: pydantic.ValidationInfo) -> object:
    if info.context and info.context.get('portable'):
        return modulation_contract.exact_seconds(value)
    return value


class EventBinding(Model):
    name: modulation_contract.Identifier
    kind: Literal['key', 'velocity']

    model_config = pydantic.ConfigDict(revalidate_instances='always')


class ControlBinding(Model):
    name: modulation_contract.Identifier
    kind: Literal['control'] = 'control'
    control: modulation_contract.Identifier
    smoothing: Annotated[
        control.Rational,
        units.unit_validator('second', exact=True),
        pydantic.BeforeValidator(portable_smoothing),
    ] = Field(default=Fraction(1, 200), ge=0)

    model_config = pydantic.ConfigDict(revalidate_instances='always')


class ReleaseTiming(StrEnum):
    event = auto()
    voice = auto()


class GeneratorBinding(Model):
    name: modulation_contract.Identifier
    kind: Literal['envelfo'] = 'envelfo'
    reference: modulation_contract.Identifier
    output: modulation_contract.Identifier | None = None
    release_timing: ReleaseTiming = ReleaseTiming.event

    model_config = pydantic.ConfigDict(revalidate_instances='always')


class FollowerBinding(Model):
    name: modulation_contract.Identifier
    kind: Literal['follower'] = 'follower'
    processor: modulation_contract.Identifier

    model_config = pydantic.ConfigDict(revalidate_instances='always')


class EnvelfoEventConnection(envelfo_contract.Definition):
    source: modulation_contract.Identifier
    port: Annotated[str, pydantic.AfterValidator(envelfo_contract.text)] = Field(
        min_length=1
    )
    destination: modulation_contract.Identifier
    cue: modulation_contract.Identifier
    every: int = Field(default=1, ge=1, strict=True)
    offset: int = Field(default=0, ge=0, strict=True)
    probability: UnitInterval = 1.0
    delay: Annotated[control.Rational, units.unit_validator('second', exact=True)] = (
        Field(default=Fraction(0), ge=0)
    )

    @model_validator(mode='before')
    @classmethod
    def portable_delay(cls, value: object, info: pydantic.ValidationInfo) -> object:
        if (
            info.context
            and info.context.get('portable')
            and isinstance(value, dict)
            and 'delay' in value
        ):
            return value | {'delay': modulation_contract.exact_seconds(value['delay'])}
        return value


Binding = Annotated[
    EventBinding | ControlBinding | GeneratorBinding | FollowerBinding,
    Field(discriminator='kind'),
]


class GeneratorRequirement(StrEnum):
    output = auto()
    domain = auto()
    release = auto()


class ConnectionRequirement(StrEnum):
    source_port = auto()
    destination_cue = auto()


class UnresolvedGeneratorBinding(Model):
    kind: Literal['generator'] = 'generator'
    binding: GeneratorBinding
    checks: list[GeneratorRequirement]


class UnresolvedEventConnection(Model):
    connection: EnvelfoEventConnection
    checks: list[ConnectionRequirement]


class BindingValidation(Model):
    unresolved_bindings: list[UnresolvedGeneratorBinding | FollowerBinding]
    unresolved_connections: list[UnresolvedEventConnection]
    unresolved_targets: list[modulation.Target]


def validate_generator_bindings(
    definition: modulation.Modulation,
    bindings: list[Binding],
    controls: dict[str, ControlDeclaration],
    generators: dict[str, Generator],
    connections: list[EnvelfoEventConnection],
    *,
    max_records: int = 10000,
) -> BindingValidation:
    """Validate available generator facts and report every external obligation."""
    context = {
        'portable': True,
        'max_records': envelfo_contract.record_limit(max_records),
    }
    data = {
        'modulation': definition,
        'bindings': bindings,
        'controls': controls,
        'envelfos': generators,
        'event_connections': connections,
    }
    envelfo_contract.preparation_records(data, max_records)
    definition = modulation.Modulation.model_validate(definition, context=context)
    bindings = pydantic.TypeAdapter(list[Binding]).validate_python(
        bindings, context=context
    )
    controls = pydantic.TypeAdapter(
        dict[modulation_contract.Identifier, ControlDeclaration]
    ).validate_python(controls, context=context)
    generators = pydantic.TypeAdapter(
        dict[modulation_contract.Identifier, Generator]
    ).validate_python(generators, context=context)
    connections = pydantic.TypeAdapter(list[EnvelfoEventConnection]).validate_python(
        connections, context=context
    )
    return _validate_available_bindings(
        definition, bindings, controls, generators, connections
    )


def _validate_available_bindings(
    definition: Modulation,
    bindings: list[Binding],
    controls: dict[str, ControlDeclaration] | None,
    generators: dict[str, Generator],
    connections: list[EnvelfoEventConnection],
) -> BindingValidation:
    sources = _binding_sources(definition, bindings)
    _inline_generators(generators)
    unresolved: list[UnresolvedGeneratorBinding | FollowerBinding] = []
    timings: dict[tuple[str, str], ReleaseTiming] = {}
    for binding in bindings:
        source = sources[binding.name]
        if isinstance(binding, ControlBinding):
            if source.scope == 'voice':
                raise ValueError('Control source must not have voice scope')
            if controls is None:
                continue
            if binding.control not in controls:
                raise ValueError(f'Unknown control: {binding.control}')
            _validate_control_source(source, controls[binding.control])
        elif isinstance(binding, EventBinding):
            _validate_event_source(source, binding, definition.routes)
        elif isinstance(binding, FollowerBinding):
            _validate_follower_source(source)
            unresolved.append(binding)
        else:
            if binding.reference not in generators:
                raise ValueError(f'Unknown local envelfo source: {binding.reference}')
            generator = generators[binding.reference]
            if isinstance(generator, envelfo.EnveLFOReference):
                if source.scope != generator.scope:
                    raise ValueError('Envelfo source scope must match its use')
                checks = [GeneratorRequirement.output, GeneratorRequirement.domain]
                if binding.release_timing == ReleaseTiming.voice:
                    checks.append(GeneratorRequirement.release)
                unresolved.append(
                    UnresolvedGeneratorBinding(binding=binding, checks=checks)
                )
            else:
                _validate_generator_source(source, binding, generator, timings)
    by_name = {b.name: b for b in bindings}
    events: list[UnresolvedEventConnection] = []
    for connection in connections:
        if checks := _validate_generator_connection(connection, by_name, generators):
            events.append(
                UnresolvedEventConnection(connection=connection, checks=checks)
            )
    return BindingValidation(
        unresolved_bindings=unresolved,
        unresolved_connections=events,
        unresolved_targets=[p.target for p in definition.parameters],
    )


def validate_local_bindings(
    definition: modulation.Modulation,
    bindings: list[Binding],
    controls: dict[str, ControlDeclaration],
) -> list[GeneratorBinding | FollowerBinding]:
    """Validate available facts and return references requiring external context."""
    modulation_contract.records(len(bindings) + len(controls))
    context = {'portable': True}
    definition = modulation.Modulation.model_validate(definition, context=context)
    modulation_contract.records(
        definition.record_count() + len(bindings) + len(controls)
    )
    bindings = pydantic.TypeAdapter(list[Binding]).validate_python(
        bindings, context=context
    )
    controls = pydantic.TypeAdapter(
        dict[modulation_contract.Identifier, ControlDeclaration]
    ).validate_python(controls, context=context)
    sources = _binding_sources(definition, bindings)
    unresolved: list[GeneratorBinding | FollowerBinding] = []
    for binding in bindings:
        source = sources[binding.name]
        if isinstance(binding, ControlBinding):
            if binding.control not in controls:
                raise ValueError(f'Unknown control: {binding.control}')
            _validate_control_source(source, controls[binding.control])
        elif isinstance(binding, EventBinding):
            _validate_event_source(source, binding, definition.routes)
        else:
            if isinstance(binding, FollowerBinding):
                _validate_follower_source(source)
            unresolved.append(binding)
    return unresolved


class ModulationSettings(Model):
    """Shared generator bindings and routes for voices and effect graphs."""

    envelfos: dict[Identifier, Generator] = Field(default_factory=dict)
    modulation: Modulation = Modulation()
    bindings: list[Binding] = Field(default_factory=list)
    event_connections: list[EnvelfoEventConnection] = Field(default_factory=list)
    follower_bindings: ClassVar[bool] = False

    @model_validator(mode='after')
    def local_references(self) -> Self:
        _inline_generators(self.envelfos)
        sources = _binding_sources(self.modulation, self.bindings)
        bindings = {b.name: b for b in self.bindings}
        for connection in self.event_connections:
            _validate_generator_connection(connection, bindings, self.envelfos)
        patch_release_timings: dict[tuple[str, str], ReleaseTiming] = {}
        for binding in self.bindings:
            source = sources[binding.name]
            if isinstance(binding, FollowerBinding):
                if not self.follower_bindings:
                    raise ValueError('Follower bindings require an effect graph')
                _validate_follower_source(source)
            elif isinstance(binding, EventBinding):
                _validate_event_source(source, binding, self.modulation.routes)
            elif isinstance(binding, GeneratorBinding):
                if binding.reference not in self.envelfos:
                    raise ValueError(
                        f'Unknown local envelfo source: {binding.reference}'
                    )
                generator = self.envelfos[binding.reference]
                _validate_generator_source(
                    source, binding, generator, patch_release_timings
                )
        for parameter in self.modulation.parameters:
            generator_use = self.envelfos.get(
                parameter.target.name.removeprefix('envelfo-')
            )
            if parameter.target.name.startswith('envelfo-') and (
                generator_use is not None
                and isinstance(generator_use, envelfo.EnveLFOReference)
            ):
                if parameter.scope != generator_use.scope:
                    raise ValueError('Envelfo parameter scope must match its use')
                continue
            unit, default = self.parameter_definition(parameter.target)
            if parameter.unit != unit or parameter.default != default:
                raise ValueError(
                    'Parameter unit and default must match the bound setting'
                )
        return self

    def parameter_definition(self, target: Target) -> tuple[Unit, float]:
        raise ValueError(f'Unknown modulation target {target.name}.{target.parameter}')


class TargetMinimum(StrEnum):
    unrestricted = auto()
    nonnegative = auto()
    positive = auto()

    @classmethod
    def for_field(cls, field: str) -> 'TargetMinimum':
        if field == 'amplitude':
            return cls.nonnegative
        if field in ('resonance', 'q'):
            return cls.positive
        return cls.unrestricted

    def validate(self, minimum: float) -> None:
        if self == TargetMinimum.nonnegative and minimum < 0:
            raise ValueError('Amplitude requires a nonnegative parameter domain')
        if self == TargetMinimum.positive and minimum <= 0:
            raise ValueError('Resonance requires a positive parameter domain')


class ResolvedTarget(Model):
    unit: Unit
    default_value: float
    duration: Fraction | None = None
    scope: control.Scope | None = None
    minimum: TargetMinimum = TargetMinimum.unrestricted


class UnresolvedGeneratorTarget(Model):
    scope: control.Scope


class SoundValidation(BindingValidation):
    unresolved_controls: list[modulation_contract.Identifier]

    def is_complete(self) -> bool:
        return not any(
            (
                self.unresolved_controls,
                self.unresolved_bindings,
                self.unresolved_connections,
                self.unresolved_targets,
            )
        )

    def require_complete(self) -> None:
        if not self.is_complete():
            raise ValueError('Sound settings need external context')


class SoundSettings(ModulationSettings):
    processing: Processing = Processing()
    envelope: Envelope | None = None

    @model_validator(mode='wrap')
    @classmethod
    def portable_sound_settings(
        cls,
        value: object,
        handler: pydantic.ModelWrapValidatorHandler[Self],
        info: pydantic.ValidationInfo,
    ) -> Self:
        if not (info.context and info.context.get('portable')):
            return handler(value)
        maximum = envelfo_contract.record_limit(info.context.get('max_records', 10000))
        envelfo_contract.preparation_records(value, maximum)
        if isinstance(value, Model):
            data = envelfo_contract.definition_data(value)
            for name in ('processing', 'modulation', 'envelope'):
                if name in data and envelfo_contract.omits_default_record(value, name):
                    data.pop(name)
            value = data
        result = handler(value)
        for name in result.envelfos:
            _PORTABLE_IDENTIFIER.validate_python(name, context=info.context)
        sources = {s.name: s for s in result.modulation.sources}
        for binding in result.bindings:
            if (
                isinstance(binding, ControlBinding)
                and sources[binding.name].scope == 'voice'
            ):
                raise ValueError('Control source must not have voice scope')
        return result

    @model_validator(mode='after')
    def sound_parameters(self) -> Self:
        if self.envelope is not None and (
            self.envelope.scope != control.Scope.voice
            or self.envelope.polarity != control.Polarity.unipolar
        ):
            raise ValueError('Amplitude envelope must be unipolar and voice scoped')
        for parameter in self.modulation.parameters:
            TargetMinimum.for_field(parameter.target.parameter).validate(
                parameter.minimum
            )
            if parameter.target.name == 'envelope':
                generator = self.envelope
            elif parameter.target.name.startswith('envelfo-'):
                generator_use = self.envelfos.get(
                    parameter.target.name.removeprefix('envelfo-')
                )
                generator = (
                    generator_use
                    if generator_use and isinstance(generator_use, envelfo.Envelope)
                    else None
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
                'envelfo-'
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
                _validate_control_source(
                    sources[binding.name], controls[binding.control]
                )

    def resolve_target(
        self, target: Target
    ) -> ResolvedTarget | UnresolvedGeneratorTarget:
        prefix = 'envelfo-'
        if target.name.startswith(prefix) and isinstance(
            generator := self.envelfos.get(target.name.removeprefix(prefix)),
            envelfo.EnveLFOReference,
        ):
            return UnresolvedGeneratorTarget(scope=generator.scope)
        timing = _envelope_target(self, target)
        if timing is not None:
            return timing
        unit, default = self.parameter_definition(target)
        return ResolvedTarget(
            unit=unit,
            default_value=default,
            minimum=TargetMinimum.for_field(target.parameter),
        )

    def validate_context(
        self,
        controls: dict[str, ControlDeclaration] | None = None,
        *,
        max_records: int = 10000,
    ) -> SoundValidation:
        """Validate portable settings and report missing context."""
        count = envelfo_contract.preparation_records(self, max_records)
        envelfo_contract.check_records(
            count + (len(controls) if controls is not None else 0), max_records
        )
        context = {'portable': True, 'max_records': max_records}
        settings = type(self).model_validate(self, context=context)
        if controls is not None:
            controls = pydantic.TypeAdapter(
                dict[modulation_contract.Identifier, ControlDeclaration]
            ).validate_python(controls, context=context)
        checks = _validate_available_bindings(
            settings.modulation,
            settings.bindings,
            controls,
            settings.envelfos,
            settings.event_connections,
        )
        return SoundValidation(
            unresolved_bindings=checks.unresolved_bindings,
            unresolved_connections=checks.unresolved_connections,
            unresolved_targets=[
                p.target
                for p in settings.modulation.parameters
                if isinstance(
                    settings.resolve_target(p.target), UnresolvedGeneratorTarget
                )
            ],
            unresolved_controls=[
                b.control
                for b in settings.bindings
                if controls is None and isinstance(b, ControlBinding)
            ],
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
    timing = _envelope_target(settings, target)
    if timing is not None:
        return timing.unit, timing.default_value
    raise ValueError(f'Unknown local parameter: {target.name}.{target.parameter}')


def _envelope_target(settings: SoundSettings, target: Target) -> ResolvedTarget | None:
    definition: Envelope | None = None
    clock: control.Clock | None = None
    if target.name == 'envelope' and settings.envelope is not None:
        definition = settings.envelope
        clock = definition.clock
    elif target.name.startswith('envelfo-'):
        generator_use = settings.envelfos.get(target.name.removeprefix('envelfo-'))
        if generator_use is not None and isinstance(generator_use, envelfo.Envelope):
            definition = generator_use
            clock = generator_use.clock
    if definition is not None:
        for phase, segments in (
            ('on', definition.segments),
            ('release', definition.release),
        ):
            for index, segment in enumerate(segments):
                if target.parameter == f'{phase}-{index}-time_constant' and isinstance(
                    segment, ExponentialApproach
                ):
                    return ResolvedTarget(
                        unit=Unit.seconds,
                        default_value=float(segment.time_constant),
                        scope=definition.scope,
                    )
                if target.parameter == f'{phase}-{index}-duration':
                    if not isinstance(segment, Segment):
                        raise ValueError(
                            'indefinite segment duration cannot be modulated'
                        )
                    unit = (
                        modulation.Unit.seconds
                        if clock == control.Clock.seconds
                        else modulation.Unit.beats
                    )
                    return ResolvedTarget(
                        unit=unit,
                        default_value=float(segment.duration),
                        duration=segment.duration,
                        scope=definition.scope,
                    )
    return None


def spatial_bounds(settings: SoundSettings, target: str) -> tuple[float, float]:
    """Conservative route bounds include the neutral contribution during activation."""
    low = high = getattr(settings.processing, target)
    multipliers: list[tuple[float, float]] = []
    weighted = {
        b.name
        for b in settings.bindings
        if isinstance(b, GeneratorBinding)
        and isinstance((body := settings.envelfos[b.reference]), LFO)
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


def _binding_sources(
    definition: Modulation, bindings: list[Binding]
) -> dict[str, modulation.Source]:
    unique((b.name for b in bindings), 'binding ID')
    sources = {s.name: s for s in definition.sources}
    if sources.keys() != {b.name for b in bindings}:
        raise ValueError('Each modulation source requires exactly one binding')
    return sources


def _validate_control_source(
    source: modulation.Source, declaration: ControlDeclaration
) -> None:
    minimum = -1 if declaration.polarity == control.Polarity.bipolar else 0
    if source.scope == 'voice' or (source.minimum, source.maximum) != (minimum, 1):
        raise ValueError(
            'ControlDeclaration source must match its declared domain and control scope'
        )


def _validate_follower_source(source: modulation.Source) -> None:
    if source.scope != 'voice' or source.minimum != 0:
        raise ValueError('Follower sources require voice scope and minimum zero')


def _validate_event_source(
    source: modulation.Source, binding: EventBinding, routes: list[modulation.Route]
) -> None:
    if source.scope != 'voice':
        raise ValueError('NoteKey and velocity bindings require voice scope')
    if binding.kind == 'key':
        if not source.minimum.is_integer() or not source.maximum.is_integer():
            raise ValueError('NoteKey source bounds must be integers')
        if any(
            not p.input.is_integer()
            for r in routes
            if r.source == source.name
            for p in r.points
        ):
            raise ValueError('NoteKey mapping inputs must be integers')
    elif (source.minimum, source.maximum) != (0, 1):
        raise ValueError('Velocity source domain must be [0, 1]')


def _inline_generators(generators: dict[str, Generator]) -> None:
    for generator in generators.values():
        if isinstance(generator, LFO) and isinstance(
            generator.rate, envelfo.ParameterReference
        ):
            raise ValueError('inline LFO rate cannot reference a public parameter')
        if isinstance(generator, Envelope) and generator.initial == 'current':
            raise ValueError('current envelope initial requires a parent stage')


def _validate_generator_source(
    source: modulation.Source,
    binding: GeneratorBinding,
    generator: Generator,
    timings: dict[tuple[str, str], ReleaseTiming],
) -> None:
    if isinstance(generator, Patch):
        if binding.output is None or binding.output not in generator.outputs:
            raise ValueError('Patch binding requires a named output')
        selected = generator.envelfos[generator.outputs[binding.output]]
        child = (binding.reference, generator.outputs[binding.output])
        if child in timings and timings[child] != binding.release_timing:
            raise ValueError('Patch child outputs require one release timing')
        timings[child] = binding.release_timing
    else:
        if binding.output is not None and not isinstance(
            generator, envelfo.EnveLFOReference
        ):
            raise ValueError('Only Patch bindings select named outputs')
        selected = generator
    if binding.release_timing == ReleaseTiming.voice and (
        not isinstance(selected, Envelope) or not selected.release
    ):
        raise ValueError('Voice release timing requires a releasing envelope')
    if isinstance(generator, envelfo.EnveLFOReference):
        if source.scope != generator.scope:
            raise ValueError('Envelfo source scope must match its use')
        return
    minimum = (
        0
        if isinstance(selected, Envelope)
        and selected.polarity == control.Polarity.unipolar
        else -1
    )
    if isinstance(generator, Patch) and isinstance(
        selected, (Sum, Product, Affine, Quantize, Latch, Threshold, Slew)
    ):
        assert binding.output is not None
        minimum, maximum = generator.signal_ranges[generator.outputs[binding.output]]
        if (
            source.scope != generator.scope
            or source.minimum > minimum
            or source.maximum < maximum
        ):
            raise ValueError('Patch output range exceeds its declared source domain')
        return
    if (source.scope, source.minimum, source.maximum) != (generator.scope, minimum, 1):
        raise ValueError('Generator source scope and domain must match its definition')


def _validate_generator_connection(
    connection: EnvelfoEventConnection,
    bindings: dict[str, Binding],
    generators: dict[str, Generator],
) -> list[ConnectionRequirement]:
    source, destination = (
        bindings.get(connection.source),
        bindings.get(connection.destination),
    )
    if not isinstance(source, GeneratorBinding) or not isinstance(
        destination, GeneratorBinding
    ):
        raise ValueError('Envelfo event connections require Envelfo bindings')
    origin, target = (
        generators.get(source.reference),
        generators.get(destination.reference),
    )
    if origin is None or target is None:
        raise ValueError('Envelfo event connection references an unknown Envelfo')
    if origin.scope != control.Scope.voice or target.scope != control.Scope.voice:
        raise ValueError('Envelfo event connections require voice scope')
    checks: list[ConnectionRequirement] = []
    if isinstance(origin, envelfo.EnveLFOReference):
        checks.append(ConnectionRequirement.source_port)
    else:
        if isinstance(origin, Patch):
            ports = origin.event_outputs.keys()
        elif isinstance(origin, Stages):
            ports = stage_event_ports(origin)
        elif isinstance(origin, LFO):
            if (
                origin.clock != control.Clock.seconds
                or origin.rate == 0
                or origin.reset != Reset.trigger
                or origin.delay
                or origin.fade_in
            ):
                raise ValueError('LFO event source requires a simple seconds clock')
            ports = {m.name for m in origin.markers}
        else:
            raise ValueError('Envelfo event source has no event ports')
        if connection.port not in ports:
            raise ValueError('Envelfo event connection references an unknown port')
    if isinstance(target, envelfo.EnveLFOReference):
        checks.append(ConnectionRequirement.destination_cue)
    elif not isinstance(target, Stages) or not any(
        t.event == f'cue.{connection.cue}' for t in target.transitions
    ):
        raise ValueError('Envelfo event destination has no matching cue')
    return checks
