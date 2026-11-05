"""Portable synth-instrument definitions, without audio buffer generation."""

from fractions import Fraction
from typing import Annotated, Literal, Self

from pydantic import Field, field_serializer, field_validator, model_validator
from reccy.configuration import units

from . import base, control, dx7, modulation, tx81z, wt11
from .base import Identifier, Model, unique
from .envelfo import Envelope
from .events import ControlChange, PerformanceEvent, Trigger
from .fm import FM, edge_target_name
from .interface import AudioBinding, EventType, InterfaceScore, PerformanceBinding
from .number import cents_to_ratio
from .oscillator import Oscillator
from .samples import enums
from .samples.controls import ControlDeclaration
from .samples.playback import Mapping
from .samples.processing import ChannelRoute, EventBinding, Processing, SoundSettings
from .samples.selection import Articulations, Choke, Sustain, VoicePolicy
from .segments import Segment
from .streams import AudioType
from .time import Timebase


class VoiceTemplate(SoundSettings):
    """Shared mapped synth lifecycle and channel settings."""

    name: Identifier
    mapping: Mapping
    channels: list[ChannelRoute] = Field(min_length=1)
    frequency_offset_hz: Annotated[float, units.unit_validator('hertz')] = 0
    minimum_hold_seconds: Annotated[
        control.Rational, units.unit_validator('second', exact=True)
    ] = Field(default=Fraction(0), ge=0)
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
        segments=[Segment(duration=0, to=1)],
        release=[Segment(duration=0, to=0)],
    )


class NoiseVoice(VoiceTemplate):
    noise: Literal['white']
    envelope: Envelope = Envelope(
        segments=[Segment(duration=0, to=1)],
        release=[Segment(duration=0, to=0)],
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
    fm: FM

    @model_validator(mode='after')
    def fm_profile(self) -> Self:
        if self.envelope is not None:
            raise ValueError(
                'FM uses operator envelopes, not a second amplitude envelope'
            )
        for p in self.modulation.parameters:
            if p.target.name == 'fm' or p.target.name.startswith(
                ('operator-', 'edge-')
            ):
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
        if target.name == 'fm' and target.parameter == 'carrier_level':
            return modulation.Unit.ratio, self.fm.carrier_level
        for o in self.fm.operators:
            if target.name == f'operator-{o.name}':
                if target.parameter == 'ratio':
                    return modulation.Unit.ratio, o.ratio
                if target.parameter == 'tuning_cents':
                    return modulation.Unit.cents, o.tuning_cents
        for edge in self.fm.edges:
            if (
                target.name == f'edge-{edge_target_name(edge)}'
                and target.parameter == 'index'
            ):
                return modulation.Unit.radians, edge.index
        return super().parameter_definition(target)


class YamahaVoiceTemplate(VoiceTemplate):
    """Shared Yamaha envelope ownership and normalized hardware controls."""

    @model_validator(mode='after')
    def yamaha_envelope(self) -> Self:
        if self.envelope is not None:
            raise ValueError('Yamaha voices use patch operator envelopes')
        for p in self.modulation.parameters:
            if p.target.name == 'yamaha':
                minimum = -1 if p.target.parameter == 'pitch_bend' else 0
                if p.minimum < minimum or p.maximum > 1:
                    raise ValueError(
                        'Yamaha controller domain exceeds its normalized range'
                    )
        return self

    def parameter_definition(
        self, target: modulation.Target
    ) -> tuple[modulation.Unit, float]:
        if target.name == 'yamaha' and target.parameter in (
            'pitch_bend',
            'modulation_wheel',
            'breath',
            'foot',
        ):
            return modulation.Unit.ratio, 0.0
        return super().parameter_definition(target)


class YamahaDX7Voice(YamahaVoiceTemplate):
    """A lossless Yamaha patch with dedicated rate/level envelope semantics."""

    yamaha: Literal['dx7'] = 'dx7'
    patch: dx7.DX7Voice
    performance: dx7.DX7Performance = Field(default_factory=dx7.DX7Performance)

    @field_validator('patch', mode='before', json_schema_input_type=str)
    @classmethod
    def decode_patch(cls, value: object) -> object:
        return (
            dx7.DX7Voice(data=bytes.fromhex(value)) if isinstance(value, str) else value
        )

    @field_serializer('patch', when_used='json')
    def encode_patch(self, value: dx7.DX7Voice) -> str:
        return value.data.hex()


class YamahaTX81ZVoice(YamahaVoiceTemplate):
    """Explicitly paired TX81Z VCED and ACED edit buffers."""

    yamaha: Literal['tx81z'] = 'tx81z'
    channels: list[ChannelRoute] = Field(default_factory=list)
    patch: tx81z.TX81ZVoice
    additional: tx81z.TX81ZAdditional

    def parameter_definition(
        self, target: modulation.Target
    ) -> tuple[modulation.Unit, float]:
        if target.name == 'yamaha' and target.parameter == 'portamento':
            return modulation.Unit.ratio, 1.0
        return super().parameter_definition(target)

    @field_validator('patch', mode='before', json_schema_input_type=str)
    @classmethod
    def decode_patch(cls, value: object) -> object:
        return (
            tx81z.TX81ZVoice(data=bytes.fromhex(value))
            if isinstance(value, str)
            else value
        )

    @field_validator('additional', mode='before', json_schema_input_type=str)
    @classmethod
    def decode_additional(cls, value: object) -> object:
        return (
            tx81z.TX81ZAdditional(data=bytes.fromhex(value))
            if isinstance(value, str)
            else value
        )

    @field_serializer('patch', 'additional', when_used='json')
    def encode_patch(self, value: tx81z.TX81ZVoice | tx81z.TX81ZAdditional) -> str:
        return value.data.hex()


class YamahaWT11Voice(YamahaVoiceTemplate):
    """WT11 VCED, ACED and ACED2, retaining its distinct pitch and bias data."""

    yamaha: Literal['wt11'] = 'wt11'
    patch: wt11.WT11Voice
    additional: wt11.WT11Additional
    additional2: wt11.WT11Additional2

    def parameter_definition(
        self, target: modulation.Target
    ) -> tuple[modulation.Unit, float]:
        if target.name == 'yamaha' and target.parameter in ('aftertouch', 'portamento'):
            return (
                modulation.Unit.ratio,
                1.0 if target.parameter == 'portamento' else 0.0,
            )
        return super().parameter_definition(target)

    @field_validator('patch', mode='before', json_schema_input_type=str)
    @classmethod
    def decode_patch(cls, value: object) -> object:
        return (
            wt11.WT11Voice(data=bytes.fromhex(value))
            if isinstance(value, str)
            else value
        )

    @field_validator('additional', mode='before', json_schema_input_type=str)
    @classmethod
    def decode_additional(cls, value: object) -> object:
        return (
            wt11.WT11Additional(data=bytes.fromhex(value))
            if isinstance(value, str)
            else value
        )

    @field_validator('additional2', mode='before', json_schema_input_type=str)
    @classmethod
    def decode_additional2(cls, value: object) -> object:
        return (
            wt11.WT11Additional2(data=bytes.fromhex(value))
            if isinstance(value, str)
            else value
        )

    @field_serializer('patch', 'additional', 'additional2', when_used='json')
    def encode_patch(
        self, value: wt11.WT11Voice | wt11.WT11Additional | wt11.WT11Additional2
    ) -> str:
        return value.data.hex()


type SynthSource = (
    SynthVoice
    | FMVoice
    | NoiseVoice
    | YamahaDX7Voice
    | YamahaTX81ZVoice
    | YamahaWT11Voice
)


class TX81ZOutput(Model):
    """Explicit raw-voice sum, shared DAC, then host processing and routing."""

    name: Identifier
    voices: list[Identifier] = Field(min_length=1)
    channels: list[ChannelRoute] = Field(min_length=1)
    processing: Processing = Processing()

    @model_validator(mode='after')
    def output_values(self) -> Self:
        unique(self.voices, 'TX81Z output voice')
        unique(((c.input, c.output) for c in self.channels), 'channel route')
        if self.processing != Processing(
            volume_db=self.processing.volume_db,
            invert_polarity=self.processing.invert_polarity,
            filters=self.processing.filters,
            filter_order=self.processing.filter_order,
        ):
            raise ValueError('TX81Z output processing supports gain and filters only')
        return self


class TX81ZLFOGroup(Model):
    """Explicit performance LFO owners and per-template modulation selectors."""

    name: Identifier
    first: Identifier
    second: Identifier | None = None
    routes: dict[Identifier, Literal['off', 'first', 'second', 'vibrato']]

    @model_validator(mode='after')
    def lfo_values(self) -> Self:
        if self.first == self.second:
            raise ValueError('TX81Z LFO owners must be distinct')
        if self.first not in self.routes or (
            self.second is not None and self.second not in self.routes
        ):
            raise ValueError('TX81Z LFO owners must be group members')
        if self.second is None and 'second' in self.routes.values():
            raise ValueError('TX81Z second LFO routing requires an owner')
        return self


class SynthInstrument(Model):
    """Synth voice templates and their shared performance declarations."""

    controls: dict[base.Identifier, ControlDeclaration] = Field(default_factory=dict)
    voice_policy: VoicePolicy | None = None
    sustain: Sustain | None = None
    articulations: Articulations | None = None
    voices: list[SynthSource] = Field(min_length=1)
    tx81z_outputs: list[TX81ZOutput] = Field(default_factory=list)
    tx81z_lfos: list[TX81ZLFOGroup] = Field(default_factory=list)

    @model_validator(mode='after')
    def instrument_values(self) -> Self:
        unique((v.name for v in self.voices), 'synth voice ID')
        unique((o.name for o in self.tx81z_outputs), 'TX81Z output ID')
        members = [v for o in self.tx81z_outputs for v in o.voices]
        unique(members, 'TX81Z output membership')
        templates = {v.name: v for v in self.voices}
        unique((g.name for g in self.tx81z_lfos), 'TX81Z LFO group ID')
        unique((n for g in self.tx81z_lfos for n in g.routes), 'TX81Z LFO membership')
        for group in self.tx81z_lfos:
            if any(
                not isinstance(templates.get(n), YamahaTX81ZVoice) for n in group.routes
            ):
                raise ValueError('TX81Z LFO groups require existing TX81Z templates')
        for name in members:
            voice = templates.get(name)
            if not isinstance(voice, YamahaTX81ZVoice):
                raise ValueError('TX81Z outputs require existing TX81Z templates')
            if voice.channels:
                raise ValueError('Grouped TX81Z voices must omit individual routes')
            if voice.processing != Processing(
                tuning_cents=voice.processing.tuning_cents
            ) or any(
                p.target.name != 'yamaha'
                and (p.target.name, p.target.parameter)
                != ('processing', 'tuning_cents')
                for p in voice.modulation.parameters
            ):
                raise ValueError(
                    'Grouped TX81Z voices allow tuning and Yamaha controls only'
                )
        if any(not v.channels and v.name not in members for v in self.voices):
            raise ValueError('Unrouted TX81Z voices require output membership')
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
            if any(
                g.scope != control.Scope.voice
                for g in voice.envelfos.values()
                if g is not None and g.kind == 'envelope'
            ):
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
        for voice in [*self.body.voices, *self.body.tx81z_outputs]:
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
