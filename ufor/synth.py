"""Portable synth-instrument definitions, without audio buffer generation."""

from typing import Literal, Self

from pydantic import Field, model_validator

from . import base, control
from .base import Identifier, Model, Text, unique
from .envelope import Envelope, Segment
from .events import ControlChange, PerformanceEvent, Trigger
from .interface import AudioBinding, EventType, InterfaceScore, PerformanceBinding
from .oscillator import Oscillator
from .samples import enums
from .samples.controls import Control
from .samples.playback import Mapping
from .samples.processing import ChannelRoute, EventBinding, SoundSettings
from .samples.selection import Articulations, Choke, Sustain, VoicePolicy
from .streams import AudioType
from .time import Timebase


class SynthVoice(SoundSettings):
    """One mapped oscillator voice template."""

    name: Identifier
    mapping: Mapping
    channels: list[ChannelRoute] = Field(min_length=1)
    oscillator: Oscillator
    trigger: enums.TriggerKind = enums.TriggerKind.start
    choke_group: Identifier | None = None
    chokes: list[Choke] = Field(default_factory=list)
    articulations: list[Identifier] = Field(default_factory=list)
    envelope: Envelope = Envelope(
        segments=[Segment(duration=0, target=1)],
        release=[Segment(duration=0, target=0)],
    )

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


class SynthInstrument(Model):
    """Synth voice templates and their shared performance declarations."""

    controls: dict[base.Identifier, Control] = Field(default_factory=dict)
    voice_policy: VoicePolicy | None = None
    sustain: Sustain | None = None
    articulations: Articulations | None = None
    voices: list[SynthVoice] = Field(min_length=1)

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
                            'Key source domain must cover the voice mapping'
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

    def require_control(self, name: str) -> Control:
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
    tags: list[Text] = Field(default_factory=list)
    timebases: list[Timebase] = Field(min_length=1)
    body: SynthInstrument

    @model_validator(mode='after')
    def public_ports(self) -> Self:
        unique(self.tags, 'tag')
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
