"""Portable synth-instrument definitions, without audio buffer generation."""

from fractions import Fraction
from typing import Literal, Self

from pydantic import Field, model_validator

from . import base, control, modulation
from .base import Identifier, Model, unique
from .envelope import Envelope, Segment
from .events import ControlChange, PerformanceEvent, Trigger
from .fm import FM, FourOperatorFM
from .interface import AudioBinding, EventType, InterfaceScore, PerformanceBinding
from .number import cents_to_ratio
from .oscillator import Oscillator
from .samples import enums
from .samples.controls import ControlDeclaration
from .samples.playback import Mapping
from .samples.processing import ChannelRoute, EventBinding, SoundSettings
from .samples.selection import Articulations, Choke, Sustain, VoicePolicy
from .streams import AudioType
from .time import Timebase


class VoiceTemplate(SoundSettings):
    """Shared mapped synth lifecycle and channel settings."""

    name: Identifier
    mapping: Mapping
    channels: list[ChannelRoute] = Field(min_length=1)
    frequency_offset_hz: float = 0
    minimum_hold_seconds: control.Rational = Field(default=Fraction(0), ge=0)
    trigger: enums.TriggerKind = enums.TriggerKind.start
    choke_group: Identifier | None = None
    chokes: list[Choke] = Field(default_factory=list)
    articulations: list[Identifier] = Field(default_factory=list)

    @model_validator(mode='after')
    def voice_values(self) -> Self:
        unique(self.articulations, 'articulation reference')
        unique((c.group for c in self.chokes), 'choke target')
        unique(((c.input, c.output) for c in self.channels), 'channel route')
        if self.trigger in (
            enums.TriggerKind.sustain_press,
            enums.TriggerKind.sustain_release,
        ):
            if self.mapping.event_key is None:
                raise ValueError('Sustain voice requires mapping.event_key')
        elif self.mapping.event_key is not None:
            raise ValueError('event_key is only allowed for sustain voices')
        return self


class SynthVoice(VoiceTemplate):
    oscillator: Oscillator
    synchronize_oscillator: bool = False
    envelope: Envelope = Envelope(
        segments=[Segment(duration=0, target=1)],
        release=[Segment(duration=0, target=0)],
    )


class NoiseVoice(VoiceTemplate):
    noise: Literal['white']
    envelope: Envelope = Envelope(
        segments=[Segment(duration=0, target=1)],
        release=[Segment(duration=0, target=0)],
    )

    @model_validator(mode='after')
    def noise_profile(self) -> Self:
        if (
            self.mapping.pitch_tracking
            or self.frequency_offset_hz
            or self.processing.tuning_cents
        ):
            raise ValueError(
                'Noise does not support pitch tracking, offsets, or tuning'
            )
        if any(
            p.target.name == 'processing' and p.target.parameter == 'tuning_cents'
            for p in self.modulation.parameters
        ):
            raise ValueError('Noise does not support tuning modulation')
        return self


class FMVoice(VoiceTemplate):
    fm: FM | FourOperatorFM

    @model_validator(mode='after')
    def fm_profile(self) -> Self:
        if self.envelope is not None:
            raise ValueError(
                'FM uses operator envelopes, not a second amplitude envelope'
            )
        for p in self.modulation.parameters:
            if p.target.name == 'fm' or p.target.name.startswith('operator-'):
                if p.target.parameter == 'ratio' and p.minimum <= 0:
                    raise ValueError('FM ratios require a positive domain')
                if (
                    p.target.parameter in ('index', 'feedback', 'carrier_level')
                    and p.minimum < 0
                ):
                    raise ValueError(
                        'FM levels and indices require nonnegative domains'
                    )
        return self

    def parameter_definition(
        self, target: modulation.Target
    ) -> tuple[modulation.Unit, float]:
        if isinstance(self.fm, FourOperatorFM):
            if target.name == 'fm' and target.parameter == 'carrier_level':
                return modulation.Unit.ratio, self.fm.carrier_level
            for operator in self.fm.operators:
                if target.name == f'operator-{operator.name}':
                    if target.parameter == 'ratio':
                        return modulation.Unit.ratio, operator.ratio
                    if target.parameter == 'tuning_cents':
                        return modulation.Unit.cents, operator.tuning_cents
            for edge in self.fm.edges:
                if target.name == f'edge-{edge.source}-{edge.destination}':
                    if target.parameter == 'index':
                        return modulation.Unit.radians, edge.index
            return super().parameter_definition(target)
        if target.name == 'fm':
            if target.parameter == 'index':
                return modulation.Unit.radians, self.fm.connection.index
            if target.parameter == 'feedback':
                return modulation.Unit.radians, self.fm.feedback
            if target.parameter == 'carrier_level':
                return modulation.Unit.ratio, self.fm.carrier_level
        for o in self.fm.operators:
            if target.name == f'operator-{o.name}':
                if target.parameter == 'ratio':
                    return modulation.Unit.ratio, o.ratio
                if target.parameter == 'tuning_cents':
                    return modulation.Unit.cents, o.tuning_cents
        return super().parameter_definition(target)


class SynthInstrument(Model):
    """Synth voice templates and their shared performance declarations."""

    controls: dict[base.Identifier, ControlDeclaration] = Field(default_factory=dict)
    voice_policy: VoicePolicy | None = None
    sustain: Sustain | None = None
    articulations: Articulations | None = None
    voices: list[SynthVoice | FMVoice | NoiseVoice] = Field(min_length=1)

    @model_validator(mode='after')
    def instrument_values(self) -> Self:
        unique((v.name for v in self.voices), 'synth voice ID')
        if self.sustain is not None:
            declared = self.require_control(self.sustain.control)
            if declared.polarity != control.Polarity.unipolar:
                raise ValueError('Sustain requires a unipolar control')
        articulations = set(self.articulations.ids) if self.articulations else set()
        if self.articulations is not None:
            for switch in self.articulations.controls:
                declared = self.require_control(switch.control)
                declared.validate_value(switch.minimum_value)
                declared.validate_value(switch.maximum_value)
        choke_groups = {v.choke_group for v in self.voices if v.choke_group}
        for voice in self.voices:
            voice.validate_controls(self.controls)
            for binding in voice.bindings:
                if isinstance(binding, EventBinding) and binding.kind == 'key':
                    source = next(
                        s for s in voice.modulation.sources if s.name == binding.name
                    )
                    if not (
                        source.minimum
                        <= voice.mapping.lowest_key
                        <= voice.mapping.highest_key
                        <= source.maximum
                    ):
                        raise ValueError(
                            'NoteKey source domain must cover the voice mapping'
                        )
            if any(p.scope != control.Scope.voice for p in voice.modulation.parameters):
                raise ValueError('Synth voice parameters must have voice scope')
            if any(g.scope != control.Scope.voice for g in voice.envelopes.values()):
                raise ValueError('Synth voice envelopes must have voice scope')
            if (
                voice.trigger
                in (
                    enums.TriggerKind.sustain_press,
                    enums.TriggerKind.sustain_release,
                )
                and self.sustain is None
            ):
                raise ValueError('Sustain voices require a sustain control')
            if missing := set(voice.articulations) - articulations:
                raise ValueError(
                    f'Synth voice {voice.name}: unknown articulations {sorted(missing)}'
                )
            for choke in voice.chokes:
                if choke.group not in choke_groups:
                    raise ValueError(
                        f'Synth voice {voice.name}: unknown choke group {choke.group}'
                    )
        return self

    def require_control(self, name: str) -> ControlDeclaration:
        if name not in self.controls:
            raise ValueError(f'Unknown control: {name}')
        return self.controls[name]

    def validate_event(self, event: PerformanceEvent) -> None:
        if isinstance(event, Trigger):
            for name, value in event.controls.items():
                self.require_control(name).validate_value(value)
        elif isinstance(event, ControlChange):
            self.require_control(event.control).validate_value(event.value)


class SynthInstrumentScore(InterfaceScore):
    kind: Literal['synth_instrument'] = 'synth_instrument'
    description: str | None = None
    timebases: list[Timebase] = Field(min_length=1)
    body: SynthInstrument

    @model_validator(mode='after')
    def public_ports(self) -> Self:
        if self.parameters:
            raise ValueError('synth public parameter exports are unsupported')
        audio = [p for p in self.outputs if isinstance(p.binding, AudioBinding)]
        performance = [
            p for p in self.inputs if isinstance(p.binding, PerformanceBinding)
        ]
        if (
            len(audio) != 1
            or len(performance) != 1
            or len(self.outputs) != 1
            or len(self.inputs) != 1
        ):
            raise ValueError(
                'synth instrument requires one audio and one performance port'
            )
        output = audio[0].stream
        if not isinstance(output, AudioType):
            raise ValueError('synth instrument audio must be an audio output')
        events = performance[0].stream
        if not isinstance(events, EventType) or set(events.kinds) != {
            'trigger',
            'release',
            'control_change',
        }:
            raise ValueError(
                'synth instrument input must accept native performance events'
            )
        for voice in self.body.voices:
            if any(
                c.input != 'mono' or c.output not in output.channels
                for c in voice.channels
            ):
                raise ValueError(
                    'Synth voice channel maps require mono input and known outputs'
                )
        return self


def frequency(pitch_hz: float, tuning_cents: float) -> float:
    """Realize a prepared onset pitch with the final routed tuning value."""
    return pitch_hz * cents_to_ratio(tuning_cents)
