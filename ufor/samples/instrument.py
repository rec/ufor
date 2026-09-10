"""Portable sample instrument selection and document references."""

from math import sqrt
from typing import Literal, Self

from pydantic import Field, model_validator

from .. import base, control
from ..assets import Asset, AudioDescription
from ..base import Identifier, Model, Text, unique
from ..envelope import Envelope, Segment
from ..events import ControlChange, PerformanceEvent, Trigger
from ..interface import (
    AudioBinding,
    EventType,
    InterfaceScore,
    PerformanceBinding,
)
from ..streams import AudioType
from ..time import Timebase
from . import enums
from .controls import Control
from .crossfade import ControlCrossfade, LayerCrossfade
from .playback import Mapping, Playback, Slice, SlotPlayback
from .processing import ChannelRoute, EventBinding, SoundSettings, spatial_bounds
from .selection import Articulations, Choke, Selection, Sustain


class Instrument(SoundSettings):
    envelope: Envelope = Envelope(
        segments=[Segment(duration=0, target=1)],
        release=[Segment(duration=0, target=0)],
    )
    playback: Playback = Playback()
    selections: list[Selection] = Field(default_factory=list)
    sustain: Sustain | None = None
    articulations: Articulations | None = None
    controls: dict[base.Identifier, Control] = Field(default_factory=dict)

    @model_validator(mode='after')
    def instrument_values(self) -> Self:
        unique((s.name for s in self.selections), 'selection ID')
        for parameter in self.modulation.parameters:
            target = parameter.target
            if target.name == 'processing' or target.name.startswith('eq-'):
                if parameter.scope != control.Scope.voice:
                    raise ValueError(
                        'Instrument processing is per voice, before mixing'
                    )
        if self.sustain is not None:
            declared = self.require_control(self.sustain.control)
            if declared.polarity != control.Polarity.unipolar:
                raise ValueError('Sustain requires a unipolar control')
        if self.articulations is not None:
            for switch in self.articulations.controls:
                declared = self.require_control(switch.control)
                declared.validate_value(switch.minimum_value)
                declared.validate_value(switch.maximum_value)
        return self

    def require_control(self, name: str) -> Control:
        if name not in self.controls:
            raise ValueError(f'Unknown control: {name}')
        return self.controls[name]


class SampleSlot(SoundSettings):
    name: Identifier
    slice: Identifier
    mapping: Mapping
    channels: list[ChannelRoute] = Field(min_length=1)
    title: Text | None = None
    description: str | None = None
    tags: list[Text] = Field(default_factory=list)
    playback: SlotPlayback = SlotPlayback()
    selection: Identifier | None = None
    choke_group: Identifier | None = None
    chokes: list[Choke] = Field(default_factory=list)
    crossfades: list[LayerCrossfade] = Field(default_factory=list)
    trigger: enums.TriggerKind = enums.TriggerKind.start
    articulations: list[Identifier] = Field(default_factory=list)

    @model_validator(mode='after')
    def slot_values(self) -> Self:
        unique(self.tags, 'tag')
        unique(self.articulations, 'articulation reference')
        unique((c.group for c in self.chokes), 'choke target')
        unique(((c.input, c.output) for c in self.channels), 'channel route')
        unique(
            (
                (
                    c.input,
                    getattr(c, 'scope', None),
                    getattr(c, 'control', None),
                    c.direction,
                )
                for c in self.crossfades
            ),
            'crossfade',
        )
        for name, lfo in self.lfos.items():
            if lfo.scope != control.Scope.voice:
                raise ValueError(f'Slot LFO {name} must have voice scope')
        for fade in self.crossfades:
            bounds = None
            if fade.input == enums.Input.key:
                bounds = self.mapping.lowest_key, self.mapping.highest_key
            elif fade.input == enums.Input.velocity:
                bounds = self.mapping.minimum_velocity, self.mapping.maximum_velocity
            if (
                bounds is not None
                and not bounds[0] <= fade.start < fade.end <= bounds[1]
            ):
                raise ValueError(
                    f'Mapping must cover the {fade.input} crossfade interval'
                )
        if self.trigger in (
            enums.TriggerKind.sustain_press,
            enums.TriggerKind.sustain_release,
        ):
            if (
                self.mapping.event_key is None
                or not self.mapping.lowest_key
                <= self.mapping.event_key
                <= self.mapping.highest_key
            ):
                raise ValueError('Sustain slot mapping must contain event_key')
            if self.mapping.pitch_tracking:
                raise ValueError('Sustain samples require pitch_tracking=false')
        elif self.mapping.event_key is not None:
            raise ValueError('event_key is only allowed for sustain samples')
        return self


class SampleInstrument(Model):
    """Instrument body. Slice frames belong to each referenced native asset."""

    kind: Literal['sample_instrument'] = 'sample_instrument'
    slices: list[Slice] = Field(min_length=1)
    instrument: Instrument
    slots: list[SampleSlot] = Field(min_length=1)

    @model_validator(mode='after')
    def instrument_references(self) -> Self:
        unique((s.name for s in self.slots), 'slot ID')
        unique((s.name for s in self.slices), 'slice ID')
        slices = {s.name: s for s in self.slices}
        selections = {s.name for s in self.instrument.selections}
        groups = {s.choke_group for s in self.slots if s.choke_group is not None}
        articulations = (
            set(self.instrument.articulations.ids)
            if self.instrument.articulations
            else set()
        )
        sustain_keys: dict[tuple[str, enums.TriggerKind], int] = {}
        self.instrument.validate_controls(self.instrument.controls)
        for slot in self.slots:
            if slot.slice not in slices:
                raise ValueError(f'Unknown slice: {slot.slice}')
            sample_slice = slices[slot.slice]
            slot.validate_controls(self.instrument.controls)
            for settings in (self.instrument, slot):
                sources = {s.name: s for s in settings.modulation.sources}
                for binding in settings.bindings:
                    if isinstance(binding, EventBinding) and binding.kind == 'key':
                        source = sources[binding.name]
                        if (
                            not source.minimum
                            <= slot.mapping.lowest_key
                            <= slot.mapping.highest_key
                            <= source.maximum
                        ):
                            raise ValueError(
                                'Key source domain must cover the slot mapping'
                            )
            for fade in slot.crossfades:
                if isinstance(fade, ControlCrossfade):
                    declared = self.instrument.require_control(fade.control)
                    declared.validate_value(fade.start)
                    declared.validate_value(fade.end)
            if any(g.scope != control.Scope.voice for g in slot.envelopes.values()):
                raise ValueError('Slot envelopes must have voice scope')
            if any(p.scope != control.Scope.voice for p in slot.modulation.parameters):
                raise ValueError('Slot parameters must have voice scope')
            for target in ('pan', 'stereo_balance'):
                instrument_bounds = spatial_bounds(self.instrument, target)
                slot_bounds = spatial_bounds(slot, target)
                low = instrument_bounds[0] + slot_bounds[0]
                high = instrument_bounds[1] + slot_bounds[1]
                if low < -1 or high > 1:
                    raise ValueError(
                        f'Slot {slot.name}: combined {target} range [{low}, {high}] '
                        'exceeds [-1, 1]'
                    )
            if slot.selection is not None and slot.selection not in selections:
                raise ValueError(
                    f'Slot {slot.name}: unknown selection {slot.selection}'
                )
            if missing := set(slot.articulations) - articulations:
                raise ValueError(
                    f'Slot {slot.name}: unknown articulations {sorted(missing)}'
                )
            for choke in slot.chokes:
                if choke.group not in groups:
                    raise ValueError(
                        f'Slot {slot.name}: unknown choke group {choke.group}'
                    )
            mode = (
                slot.playback.mode
                if slot.playback.mode is not None
                else self.instrument.playback.mode
            )
            direction = (
                slot.playback.direction
                if slot.playback.direction is not None
                else self.instrument.playback.direction
            )
            if (
                slot.trigger != enums.TriggerKind.start
                and mode != enums.PlaybackMode.one_shot
            ):
                raise ValueError(
                    f'Slot {slot.name}: release/sustain triggers require one_shot'
                )
            if sample_slice.loop is not None:
                if mode != enums.PlaybackMode.while_held:
                    raise ValueError(f'Slot {slot.name}: loops require while_held')
                if (
                    direction == enums.Direction.mirror
                    and sample_slice.loop.crossfade_frames
                ):
                    raise ValueError(f'Slot {slot.name}: mirror loops cannot crossfade')
            if slot.trigger in (
                enums.TriggerKind.sustain_press,
                enums.TriggerKind.sustain_release,
            ):
                if self.instrument.sustain is None:
                    raise ValueError(
                        f'Slot {slot.name}: sustain triggers require a sustain control'
                    )
                if slot.selection is not None:
                    key = slot.selection, slot.trigger
                    if (
                        key in sustain_keys
                        and sustain_keys[key] != slot.mapping.event_key
                    ):
                        raise ValueError(
                            f'Selection {slot.selection}: '
                            'sustain alternatives must share event_key'
                        )
                    if slot.mapping.event_key is not None:
                        sustain_keys[key] = slot.mapping.event_key
        return self

    def validate_event(self, event: PerformanceEvent) -> None:
        """Check declared control domains; lifecycle ownership belongs to the player."""
        if isinstance(event, Trigger):
            for name, value in event.controls.items():
                self.instrument.require_control(name).validate_value(value)
        elif isinstance(event, ControlChange):
            self.instrument.require_control(event.control).validate_value(event.value)


class AudioAsset(Asset):
    audio: AudioDescription


class InstrumentScore(InterfaceScore):
    kind: Literal['instrument'] = 'instrument'
    description: str | None = None
    tags: list[Text] = Field(default_factory=list)
    timebases: list[Timebase] = Field(min_length=1)
    assets: list[AudioAsset] = Field(min_length=1)
    body: SampleInstrument

    @model_validator(mode='after')
    def asset_references(self) -> Self:
        unique(self.tags, 'tag')
        unique((t.name for t in self.timebases), 'timebase name')
        unique((a.name for a in self.assets), 'asset ID')
        clocks = {t.name for t in self.timebases}
        assets = {a.name: a for a in self.assets}
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
                'sample instrument requires one audio and one performance port'
            )
        output = audio[0].stream
        if not isinstance(output, AudioType):
            raise ValueError('instrument audio must be an audio output')
        events = performance[0].stream
        if not isinstance(events, EventType) or set(events.kinds) != {
            'trigger',
            'release',
            'control_change',
        }:
            raise ValueError('instrument input must accept native performance events')
        if output.timebase not in clocks or any(
            a.audio.timebase not in clocks for a in self.assets
        ):
            raise ValueError('Unknown audio timebase')
        for sample_slice in self.body.slices:
            if sample_slice.asset not in assets:
                raise ValueError(f'Unknown slice asset: {sample_slice.asset}')
            if sample_slice.end_frame > assets[sample_slice.asset].audio.frames:
                raise ValueError('Slice exceeds native asset frames')
        slices = {s.name: s for s in self.body.slices}
        for slot in self.body.slots:
            source = assets[slices[slot.slice].asset].audio
            if any(
                c.input not in source.channels or c.output not in output.channels
                for c in slot.channels
            ):
                raise ValueError('Unknown channel in slot channel map')
            for target, layout in (
                ('pan', ['mono']),
                ('stereo_balance', ['left', 'right']),
            ):
                active = any(
                    getattr(s.processing, target) != 0
                    or any(
                        r.target.name == 'processing' and r.target.parameter == target
                        for r in s.modulation.routes
                    )
                    for s in (self.body.instrument, slot)
                )
                if active:
                    if source.channels != layout or output.channels != [
                        'left',
                        'right',
                    ]:
                        raise ValueError(
                            f'{target} requires its native layout and stereo output'
                        )
                    expected = (
                        [
                            ChannelRoute(input='mono', output=c, gain=sqrt(0.5))
                            for c in output.channels
                        ]
                        if target == 'pan'
                        else [ChannelRoute(input=c, output=c, gain=1) for c in layout]
                    )
                    if slot.channels != expected:
                        raise ValueError(f'{target} requires the canonical channel map')
        return self
