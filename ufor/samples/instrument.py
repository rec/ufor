"""Portable sample instrument selection and document references."""

from math import sqrt
from typing import Literal, Self

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

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
from .controls import ControlDeclaration
from .crossfade import ControlCrossfade, LayerCrossfade
from .playback import Mapping, Playback, Slice, SlotPlayback
from .processing import ChannelRoute, EventBinding, SoundSettings, spatial_bounds
from .selection import (
    Articulations,
    Choke,
    RandomRange,
    Selection,
    Sustain,
    VoicePolicy,
)
from .variation import Variation


class SampleSettings(SoundSettings):
    envelope: Envelope = Envelope(
        segments=[Segment(duration=0, target=1)],
        release=[Segment(duration=0, target=0)],
    )
    playback: Playback = Playback()
    selections: list[Selection] = Field(default_factory=list)
    voice_policy: VoicePolicy | None = None
    sustain: Sustain | None = None
    articulations: Articulations | None = None
    controls: dict[base.Identifier, ControlDeclaration] = Field(default_factory=dict)

    @model_validator(mode='after')
    def instrument_values(self) -> Self:
        unique((s.name for s in self.selections), 'selection ID')
        for parameter in self.modulation.parameters:
            target = parameter.target
            if target.name == 'processing' or target.name.startswith(
                ('eq-', 'filter-')
            ):
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

    def require_control(self, name: str) -> ControlDeclaration:
        if name not in self.controls:
            raise ValueError(f'Unknown control: {name}')
        return self.controls[name]


class SlotGroup(SoundSettings):
    """One non-nested shared selection and sound-settings layer."""

    name: Identifier
    selection: Identifier | None = None


class SampleSlot(SoundSettings):
    name: Identifier
    slice: Identifier
    mapping: Mapping
    channels: list[ChannelRoute] = Field(min_length=1)
    title: Text | None = None
    description: str | None = None
    tags: list[Text] = Field(default_factory=list)
    playback: SlotPlayback = SlotPlayback()
    group: Identifier | None = None
    selection: Identifier | Literal[False] | None = None
    random_range: RandomRange | None = None
    take: Identifier | None = None
    microphone: Identifier | None = None
    alignment_frames: int = Field(default=0, strict=True)
    choke_group: Identifier | None = None
    chokes: list[Choke] = Field(default_factory=list)
    crossfades: list[LayerCrossfade] = Field(default_factory=list)
    trigger: enums.TriggerKind = enums.TriggerKind.start
    articulations: list[Identifier] = Field(default_factory=list)
    variation: Variation = Variation()

    @field_validator(
        'envelope',
        mode='before',
        json_schema_input_type=Envelope | Literal[False] | None,
    )
    @classmethod
    def no_envelope(cls, value: object) -> object:
        return None if value is False else value

    @model_serializer(mode='wrap')
    def authored_settings(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, object]:
        data = handler(self)
        if self.group is not None:
            for name in (
                'processing',
                'envelope',
                'envelopes',
                'lfos',
                'modulation',
                'bindings',
                'selection',
            ):
                if name not in self.model_fields_set:
                    data.pop(name, None)
            if 'envelope' in self.model_fields_set and self.envelope is None:
                data['envelope'] = False
        return data

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
            if fade.input == enums.CrossfadeInput.key:
                bounds = self.mapping.lowest_key, self.mapping.highest_key
            elif fade.input == enums.CrossfadeInput.velocity:
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


def effective_settings(slot: SampleSlot, group: SlotGroup | None) -> SoundSettings:
    """Resolve whole sound-setting categories from slot, group, then defaults."""
    fields = ('processing', 'envelope', 'envelopes', 'lfos', 'modulation', 'bindings')
    return SoundSettings.model_validate(
        {
            name: getattr(slot, name)
            if group is None or name in slot.model_fields_set
            else getattr(group, name)
            for name in fields
        }
    )


def effective_selection(slot: SampleSlot, group: SlotGroup | None) -> Identifier | None:
    if slot.selection is False:
        return None
    if slot.selection is not None:
        return slot.selection
    return group.selection if group is not None else None


class SampleInstrument(Model):
    """Sample instrument body. Slice frames belong to each referenced native asset."""

    kind: Literal['sample_instrument'] = 'sample_instrument'
    slices: list[Slice] = Field(min_length=1)
    settings: SampleSettings
    groups: list[SlotGroup] = Field(default_factory=list)
    slots: list[SampleSlot] = Field(min_length=1)

    @model_validator(mode='after')
    def instrument_references(self) -> Self:
        unique((s.name for s in self.slots), 'slot ID')
        unique((s.name for s in self.slices), 'slice ID')
        unique((g.name for g in self.groups), 'slot group ID')
        slices = {s.name: s for s in self.slices}
        selections = {s.name for s in self.settings.selections}
        slot_groups = {g.name: g for g in self.groups}
        choke_groups = {s.choke_group for s in self.slots if s.choke_group is not None}
        articulations = (
            set(self.settings.articulations.ids)
            if self.settings.articulations
            else set()
        )
        sustain_keys: dict[tuple[str, enums.TriggerKind], int] = {}
        microphone_sets: dict[tuple[str, enums.TriggerKind], set[str]] = {}
        linked_takes: dict[tuple[str, enums.TriggerKind, str], list[str]] = {}
        take_modes: dict[tuple[str, enums.TriggerKind], set[bool]] = {}
        self.settings.validate_controls(self.settings.controls)
        for group in self.groups:
            group.validate_controls(self.settings.controls)
            if group.selection is not None and group.selection not in selections:
                raise ValueError(
                    f'Slot group {group.name}: unknown selection {group.selection}'
                )
        for slot in self.slots:
            if slot.slice not in slices:
                raise ValueError(f'Unknown slice: {slot.slice}')
            sample_slice = slices[slot.slice]
            if slot.group is not None and slot.group not in slot_groups:
                raise ValueError(f'Slot {slot.name}: unknown group {slot.group}')
            group = slot_groups.get(slot.group) if slot.group is not None else None
            effective = effective_settings(slot, group)
            effective.validate_controls(self.settings.controls)
            for sound_settings in (self.settings, effective):
                sources = {s.name: s for s in sound_settings.modulation.sources}
                for binding in sound_settings.bindings:
                    if isinstance(binding, EventBinding) and binding.kind == 'key':
                        source = sources[binding.name]
                        if (
                            not source.minimum
                            <= slot.mapping.lowest_key
                            <= slot.mapping.highest_key
                            <= source.maximum
                        ):
                            raise ValueError(
                                'NoteKey source domain must cover the slot mapping'
                            )
            for fade in slot.crossfades:
                if isinstance(fade, ControlCrossfade):
                    declared = self.settings.require_control(fade.control)
                    declared.validate_value(fade.start)
                    declared.validate_value(fade.end)
            if any(
                g.scope != control.Scope.voice for g in effective.envelopes.values()
            ):
                raise ValueError('Slot envelopes must have voice scope')
            if any(
                p.scope != control.Scope.voice for p in effective.modulation.parameters
            ):
                raise ValueError('Slot parameters must have voice scope')
            for target in ('pan', 'stereo_balance'):
                instrument_bounds = spatial_bounds(self.settings, target)
                slot_bounds = spatial_bounds(effective, target)
                low = instrument_bounds[0] + slot_bounds[0]
                high = instrument_bounds[1] + slot_bounds[1]
                if low < -1 or high > 1:
                    raise ValueError(
                        f'Slot {slot.name}: combined {target} range [{low}, {high}] '
                        'exceeds [-1, 1]'
                    )
            selection = effective_selection(slot, group)
            if selection is not None and selection not in selections:
                raise ValueError(f'Slot {slot.name}: unknown selection {selection}')
            if slot.take is not None:
                if selection is None or slot.microphone is None:
                    raise ValueError(
                        'Linked takes require a selection and microphone identity'
                    )
                key = selection, slot.trigger
                take_modes.setdefault(key, set()).add(True)
                linked_takes.setdefault(
                    (selection, slot.trigger, slot.take), []
                ).append(slot.microphone)
            elif slot.microphone is not None or slot.alignment_frames:
                raise ValueError('microphone and alignment_frames require take')
            elif selection is not None:
                take_modes.setdefault((selection, slot.trigger), set()).add(False)
            if missing := set(slot.articulations) - articulations:
                raise ValueError(
                    f'Slot {slot.name}: unknown articulations {sorted(missing)}'
                )
            for choke in slot.chokes:
                if choke.group not in choke_groups:
                    raise ValueError(
                        f'Slot {slot.name}: unknown choke group {choke.group}'
                    )
            mode = (
                slot.playback.mode
                if slot.playback.mode is not None
                else self.settings.playback.mode
            )
            direction = (
                slot.playback.direction
                if slot.playback.direction is not None
                else self.settings.playback.direction
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
                if self.settings.sustain is None:
                    raise ValueError(
                        f'Slot {slot.name}: sustain triggers require a sustain control'
                    )
                if selection is not None:
                    key = selection, slot.trigger
                    if (
                        key in sustain_keys
                        and sustain_keys[key] != slot.mapping.event_key
                    ):
                        raise ValueError(
                            f'Selection {selection}: '
                            'sustain alternatives must share event_key'
                        )
                    if slot.mapping.event_key is not None:
                        sustain_keys[key] = slot.mapping.event_key
        for key, modes in take_modes.items():
            if len(modes) > 1:
                raise ValueError(f'Selection {key[0]} mixes linked and ordinary takes')
        for (selection, trigger, take), microphones in linked_takes.items():
            unique(microphones, 'microphone identity')
            key = selection, trigger
            names = set(microphones)
            if key in microphone_sets and microphone_sets[key] != names:
                raise ValueError(
                    f'Selection {selection}: take {take} has different microphones'
                )
            microphone_sets[key] = names
        return self

    def validate_event(self, event: PerformanceEvent) -> None:
        """Check declared control domains; lifecycle ownership belongs to the player."""
        if isinstance(event, Trigger):
            for name, value in event.controls.items():
                self.settings.require_control(name).validate_value(value)
        elif isinstance(event, ControlChange):
            self.settings.require_control(event.control).validate_value(event.value)


class AudioAsset(Asset):
    audio: AudioDescription


class SampleInstrumentScore(InterfaceScore):
    kind: Literal['instrument'] = 'instrument'
    description: str | None = None
    timebases: list[Timebase] = Field(min_length=1)
    assets: list[AudioAsset] = Field(min_length=1)
    body: SampleInstrument

    @model_validator(mode='after')
    def asset_references(self) -> Self:
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
        groups = {g.name: g for g in self.body.groups}
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
                    for s in (
                        self.body.settings,
                        effective_settings(slot, groups.get(slot.group)),
                    )
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
