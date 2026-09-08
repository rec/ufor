"""Read and write the representable core of SFZ files."""

import json
import math
import re
from fractions import Fraction
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from . import base, envelope, modulation
from .assets import Asset, AudioDescription
from .control import Clock, Scope
from .samples import controls, crossfade, enums, playback, processing, selection
from .samples.instrument import (
    AudioAsset,
    Instrument,
    InstrumentDocument,
    SampleInstrument,
    SampleSlot,
)
from .samples.metadata import AudioMetadata
from .streams import AudioType
from .time import Rate, Timebase


class SfzLocation(base.Model):
    kind: Literal['sfz'] = 'sfz'
    header: str
    opcode: str | None
    line: int
    column: int


class InstrumentLocation(base.Model):
    kind: Literal['instrument'] = 'instrument'
    path: str


class UnimplementedFeature(base.Model):
    location: Annotated[SfzLocation | InstrumentLocation, Field(discriminator='kind')]
    value: str | None
    reason: str


class SfzReadResult(base.Model):
    instrument: InstrumentDocument | None
    unimplemented: list[UnimplementedFeature] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.unimplemented


class SfzWriteResult(base.Model):
    contents: str
    unimplemented: list[UnimplementedFeature] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.unimplemented


class ParsedOpcode(base.Model):
    header: str
    opcode: str
    value: str
    line: int
    column: int


class ParsedRegion(base.Model):
    default_path: str
    opcodes: list[ParsedOpcode]
    line: int


class Opcode(base.Model):
    name: str
    value: str


class InstrumentMetadata(base.Model):
    version: Literal[1]
    name: str
    description: str | None
    tags: list[str]


class SlotMetadata(base.Model):
    id: str
    name: str | None
    description: str | None
    tags: list[str]


class SfzSource(base.Model):
    regions: list[ParsedRegion]
    instrument_metadata: dict[str, object]
    slot_metadata: dict[int, dict[str, object]]
    unimplemented: list[UnimplementedFeature]


def parse(text: str) -> SfzSource:
    """Parse SFZ text without opening files or invoking vendor preprocessors."""
    metadata, slots, metadata_issues = _metadata(text)
    regions, issues = _parse(text)
    if not regions and not issues:
        raise ValueError('SFZ file contains no regions')
    return SfzSource(
        regions=regions,
        instrument_metadata=metadata or {},
        slot_metadata=slots,
        unimplemented=[*issues, *metadata_issues],
    )


def sample_paths(source: SfzSource) -> list[str]:
    """Return unique portable file references for the caller to inspect and seal."""
    result: list[str] = []
    for index, region in enumerate(source.regions, 1):
        samples = [o.value for o in region.opcodes if o.opcode == 'sample']
        if not samples:
            raise ValueError(f'Region {index}: sample is required')
        if samples[-1].startswith('*'):
            continue
        path = str(
            PurePosixPath(region.default_path.replace('\\', '/'))
            / samples[-1].replace('\\', '/')
        )
        Asset.portable_path(path)
        if path not in result:
            result.append(path)
    return result


def compile(
    source: SfzSource,
    *,
    id: str,
    name: str,
    assets: dict[str, AudioMetadata],
    output_timebase: Timebase,
    output_channels: list[str],
) -> SfzReadResult:
    """Build a native document from parsed text and caller-supplied asset facts."""
    paths = sample_paths(source)
    asset_ids = {p: f'asset-{i}' for i, p in enumerate(paths, 1)}
    native_assets: list[AudioAsset] = []
    clocks = {output_timebase.id: output_timebase}
    for path in paths:
        metadata = assets[path]
        clock = Timebase(
            id=f'native-{metadata.sample_rate}',
            rate=Rate(numerator=metadata.sample_rate),
        )
        if clock.id in clocks and clocks[clock.id] != clock:
            raise ValueError('Output timebase conflicts with a native asset clock')
        clocks[clock.id] = clock
        channels = (
            ['mono']
            if metadata.channels == 1
            else ['left', 'right']
            if metadata.channels == 2
            else [f'channel-{i}' for i in range(1, metadata.channels + 1)]
        )
        native_assets.append(
            AudioAsset(
                id=asset_ids[path],
                path=path,
                encoding=metadata.encoding,
                byte_length=metadata.byte_length,
                sha256=metadata.sha256,
                audio=AudioDescription(
                    timebase=clock.id, channels=channels, frames=metadata.frames
                ),
            )
        )
    unimplemented = list(source.unimplemented)
    slots: list[SampleSlot] = []
    slices: list[playback.Slice] = []
    for index, region in enumerate(source.regions, 1):
        if (
            result := _slot(
                index, assets, asset_ids, output_channels, region, unimplemented
            )
        ) is not None:
            slot, sample_slice = result
            if metadata := source.slot_metadata.get(index):
                slot = SampleSlot.model_validate(slot.model_dump() | metadata)
            slots.append(slot)
            slices.append(sample_slice)
    document = None
    if slots:
        document = InstrumentDocument.model_validate(
            dict(
                id=id,
                name=name,
                timebases=list(clocks.values()),
                assets=native_assets,
                output=AudioType(timebase=output_timebase.id, channels=output_channels),
                body=SampleInstrument(
                    instrument=Instrument(
                        controls={'sustain': controls.Control()},
                        sustain=selection.Sustain(control='sustain'),
                    ),
                    slots=slots,
                    slices=slices,
                ),
            )
            | source.instrument_metadata
        )
    unimplemented.sort(key=_sfz_issue_position)
    return SfzReadResult(instrument=document, unimplemented=unimplemented)


def write(instrument: InstrumentDocument) -> SfzWriteResult:
    """Serialize a native instrument without reading or writing sample assets."""
    issues: list[UnimplementedFeature] = []
    _instrument_issues(instrument, issues)
    groups = _choke_groups(instrument)
    regions: list[list[str]] = []
    for i, slot in enumerate(instrument.body.slots):
        opcodes = _region(instrument, slot, i, groups, issues)
        if opcodes is None:
            continue
        metadata = '// recs:slot ' + _json(
            {
                'id': slot.id,
                'name': slot.name,
                'description': slot.description,
                'tags': slot.tags,
            }
        )
        regions.append(
            [metadata, '<region>', *(f'{o.name}={o.value}' for o in opcodes)]
        )
    if not regions:
        _issue(
            issues,
            'body.slots',
            instrument.body.slots,
            'No slot can be represented as an SFZ region',
        )
        return SfzWriteResult(contents='// Generated by recs\n', unimplemented=issues)
    lines = [
        '// Generated by recs',
        '// recs:instrument '
        + _json(
            {
                'version': 1,
                'name': instrument.name,
                'description': instrument.description,
                'tags': instrument.tags,
            }
        ),
    ]
    for region in regions:
        lines.extend(['', *region])
    return SfzWriteResult(contents='\n'.join(lines) + '\n', unimplemented=issues)


def amplitude_envelope(values: dict[str, str]) -> envelope.Envelope:
    """Translate SFZ's DAHDSR vocabulary into the one shared segment model."""
    durations = [
        Fraction(values.get(f'ampeg_{n}', '0'))
        for n in ('delay', 'attack', 'hold', 'decay')
    ]
    sustain = _number(values.get('ampeg_sustain', '100'), 'ampeg_sustain') / 100
    return envelope.Envelope(
        segments=[
            envelope.Segment(duration=d, target=t, curve=c)
            for d, t, c in zip(
                durations, [0, 1, 1, sustain], [0, 0, 0, -5], strict=True
            )
        ],
        release=[
            envelope.Segment(
                duration=Fraction(values.get('ampeg_release', '0.001')),
                target=0,
                curve=-5,
            )
        ],
    )


def _channel_routes(channels: int, outputs: list[str]) -> list[processing.ChannelRoute]:
    inputs = (
        ['mono']
        if channels == 1
        else ['left', 'right']
        if channels == 2
        else [f'channel-{i}' for i in range(1, channels + 1)]
    )
    if inputs == outputs:
        return [processing.ChannelRoute(input=c, output=c, gain=1) for c in inputs]
    if inputs == ['mono'] and outputs == ['left', 'right']:
        return [
            processing.ChannelRoute(input='mono', output=c, gain=math.sqrt(0.5))
            for c in outputs
        ]
    raise ValueError('SFZ import requires matching channels or mono-to-stereo output')


def _instrument_issues(
    document: InstrumentDocument, issues: list[UnimplementedFeature]
) -> None:
    instrument = document.body.instrument
    if instrument.selections:
        for i, value in enumerate(instrument.selections):
            _issue(
                issues,
                f'body.instrument.selections[{i}]',
                value,
                'SFZ alternate-selection behavior is not represented',
            )
    if instrument.articulations is not None:
        _issue(
            issues,
            'body.instrument.articulations',
            instrument.articulations,
            'Instrument articulation declarations require an external input binding',
        )
    canonical_sustain = selection.Sustain(control='sustain')
    canonical_controls = {'sustain': controls.Control()}
    if instrument.sustain != canonical_sustain:
        _issue(
            issues,
            'body.instrument.sustain',
            instrument.sustain,
            'SFZ only provides its implicit canonical sustain-pedal behavior',
        )
    if instrument.controls != canonical_controls:
        _issue(
            issues,
            'body.instrument.controls',
            instrument.controls,
            'Named instrument controls require an external SFZ input binding',
        )
    _sound_issues(instrument, 'body.instrument', issues)


def _sound_issues(
    settings: processing.SoundSettings,
    path: str,
    issues: list[UnimplementedFeature],
) -> None:
    for i, value in enumerate(settings.processing.equalizer):
        _issue(
            issues,
            f'{path}.processing.equalizer[{i}]',
            value,
            'Instrument equalizer bands have no implemented SFZ conversion',
        )
    for name, value in settings.envelopes.items():
        _issue(
            issues,
            f'{path}.envelopes.{name}',
            value,
            'Named instrument envelopes have no implemented SFZ conversion',
        )
    for name, value in settings.lfos.items():
        _issue(
            issues,
            f'{path}.lfos.{name}',
            value,
            'Instrument LFOs have no implemented SFZ conversion',
        )
    for i, value in enumerate(settings.modulation.routes):
        _issue(
            issues,
            f'{path}.modulation.routes[{i}]',
            value,
            'Instrument-wide modulation has no exact SFZ region conversion',
        )


def _region(
    document: InstrumentDocument,
    slot: SampleSlot,
    index: int,
    groups: dict[str, int],
    issues: list[UnimplementedFeature],
) -> list[Opcode] | None:
    path = f'body.slots[{index}]'
    sample_slice = next(s for s in document.body.slices if s.id == slot.slice)
    asset = next(a for a in document.assets if a.id == sample_slice.asset)
    sample = asset.path
    try:
        expected_channels = _channel_routes(
            len(asset.audio.channels), document.output.channels
        )
    except ValueError:
        expected_channels = []
    if slot.channels != expected_channels:
        _issue(
            issues,
            f'{path}.channels',
            slot.channels,
            'Custom channel routing has no SFZ conversion',
        )
    sample_safe = _safe_sample(sample)
    if not sample_safe:
        _issue(
            issues,
            f'{path}.sample',
            sample,
            'Sample reference contains syntax that is unsafe in portable SFZ',
        )
    mapping_eligible = _mapping_eligible(slot.mapping, path, issues)
    if not sample_safe or not mapping_eligible:
        _diagnose_omitted_slot(document, slot, path, groups, issues)
        return None

    opcodes = [Opcode(name='sample', value=sample)]
    if slot.name is not None and _safe_value(slot.name):
        opcodes.insert(0, Opcode(name='region_label', value=slot.name))
    opcodes.extend(_mapping(slot.mapping))
    opcodes.extend(_trigger_opcodes(slot, path, issues))
    opcodes.extend(_choking(slot, path, groups, issues))
    opcodes.extend(_playback_opcodes(document, slot, path, issues))
    opcodes.extend(_processing_opcodes(document, slot, path, issues))
    opcodes.extend(_envelope_opcodes(document, slot, path, issues))
    opcodes.extend(_crossfade_opcodes(slot, path, issues))
    opcodes.extend(_modulation_opcodes(slot, path, issues))
    _slot_issues(slot, path, issues)
    return opcodes


def _diagnose_omitted_slot(
    document: InstrumentDocument,
    slot: SampleSlot,
    path: str,
    groups: dict[str, int],
    issues: list[UnimplementedFeature],
) -> None:
    _trigger_opcodes(slot, path, issues)
    _choking(slot, path, groups, issues)
    _playback_opcodes(document, slot, path, issues)
    instrument = document.body.instrument.processing
    local = slot.processing
    if not slot.mapping.pitch_tracking and slot.mapping.reference_pitch_hz is not None:
        _issue(
            issues,
            f'{path}.mapping.reference_pitch_hz',
            slot.mapping.reference_pitch_hz,
            'An untracked SFZ region cannot retain a reference pitch as metadata',
        )
    if (instrument.pan + local.pan) and (
        instrument.stereo_balance + local.stereo_balance
    ):
        _issue(
            issues,
            f'{path}.processing',
            local,
            'One SFZ pan opcode cannot distinguish simultaneous pan and balance',
        )
    for i, band in enumerate(local.equalizer):
        _issue(
            issues,
            f'{path}.processing.equalizer[{i}]',
            band,
            'Instrument equalizer bands have no implemented SFZ conversion',
        )
    _envelope_opcodes(document, slot, path, issues)
    _crossfade_opcodes(slot, path, issues)
    _modulation_opcodes(slot, path, issues)
    _slot_issues(slot, path, issues)


def _mapping_eligible(
    mapping: playback.Mapping, path: str, issues: list[UnimplementedFeature]
) -> bool:
    valid = True
    if not 0 <= mapping.lowest_key <= mapping.highest_key <= 127:
        _issue(
            issues,
            f'{path}.mapping',
            mapping,
            'SFZ key bounds must be within 0 through 127',
        )
        valid = False
    for field in ('minimum_velocity', 'maximum_velocity'):
        value = getattr(mapping, field)
        if _velocity_number(value) is None:
            _issue(
                issues,
                f'{path}.mapping.{field}',
                value,
                'SFZ velocity bounds must be exact integer multiples of 1/127',
            )
            valid = False
    if mapping.event_key is not None:
        _issue(
            issues,
            f'{path}.mapping.event_key',
            mapping.event_key,
            'SFZ sustain event-key mappings require an external input binding',
        )
        valid = False
    if mapping.pitch_tracking and _pitch_key(mapping.reference_pitch_hz) is None:
        _issue(
            issues,
            f'{path}.mapping.reference_pitch_hz',
            mapping.reference_pitch_hz,
            'Reference pitch has no in-range SFZ pitch key center',
        )
        valid = False
    return valid


def _mapping(mapping: playback.Mapping) -> list[Opcode]:
    result = [
        Opcode(name='lokey', value=str(mapping.lowest_key)),
        Opcode(name='hikey', value=str(mapping.highest_key)),
        Opcode(name='lovel', value=str(_velocity_number(mapping.minimum_velocity))),
        Opcode(name='hivel', value=str(_velocity_number(mapping.maximum_velocity))),
    ]
    if mapping.pitch_tracking:
        assert mapping.reference_pitch_hz is not None
        assert (key := _pitch_key(mapping.reference_pitch_hz)) is not None
        result.append(Opcode(name='pitch_keycenter', value=str(key)))
    else:
        result.append(Opcode(name='pitch_keytrack', value='0'))
    return result


def _trigger_opcodes(
    slot: SampleSlot, path: str, issues: list[UnimplementedFeature]
) -> list[Opcode]:
    values = {
        enums.TriggerKind.start: None,
        enums.TriggerKind.release: 'release_key',
        enums.TriggerKind.logical_release: 'release',
    }
    if slot.trigger in values:
        value = values[slot.trigger]
        return [Opcode(name='trigger', value=value)] if value else []
    _issue(
        issues,
        f'{path}.trigger',
        slot.trigger,
        'Sustain-transition triggers require an external SFZ input binding',
    )
    return []


def _choke_groups(document: InstrumentDocument) -> dict[str, int]:
    groups: dict[str, int] = {}
    for slot in document.body.slots:
        if slot.choke_group is not None and slot.choke_group not in groups:
            groups[slot.choke_group] = len(groups) + 1
    return groups


def _choking(
    slot: SampleSlot,
    path: str,
    groups: dict[str, int],
    issues: list[UnimplementedFeature],
) -> list[Opcode]:
    result: list[Opcode] = []
    if slot.choke_group is not None:
        result.append(Opcode(name='group', value=str(groups[slot.choke_group])))
    if len(slot.chokes) > 1:
        for i, choke in enumerate(slot.chokes[1:], 1):
            _issue(
                issues,
                f'{path}.chokes[{i}]',
                choke,
                'An SFZ region can target only one choke group',
            )
    if not slot.chokes:
        return result
    choke = slot.chokes[0]
    if choke.mode == enums.ChokeMode.fade:
        _issue(
            issues,
            f'{path}.chokes[0]',
            choke,
            'Timed instrument fade choking has no exact SFZ off_mode',
        )
        return result
    result.extend(
        [
            Opcode(name='off_by', value=str(groups[choke.group])),
            Opcode(
                name='off_mode',
                value='fast' if choke.mode == enums.ChokeMode.immediate else 'normal',
            ),
        ]
    )
    return result


def _playback_opcodes(
    document: InstrumentDocument,
    slot: SampleSlot,
    path: str,
    issues: list[UnimplementedFeature],
) -> list[Opcode]:
    instrument = document.body.instrument.playback
    value = slot.playback
    sample_slice = next(s for s in document.body.slices if s.id == slot.slice)
    direction = value.direction if value.direction is not None else instrument.direction
    direction_path = (
        f'{path}.playback.direction'
        if value.direction is not None
        else 'body.instrument.playback.direction'
    )
    mode = value.mode if value.mode is not None else instrument.mode
    result: list[Opcode] = []
    if direction == enums.Direction.backward:
        result.append(Opcode(name='direction', value='reverse'))
    elif direction == enums.Direction.mirror:
        _issue(
            issues,
            direction_path,
            direction,
            'Mirror traversal has no exact SFZ direction',
        )
    if sample_slice.start_frame:
        result.append(Opcode(name='offset', value=str(sample_slice.start_frame)))
    if sample_slice.end_frame is not None:
        result.append(
            Opcode(name='end', value=str(_inclusive_end(sample_slice.end_frame)))
        )
    if sample_slice.loop is not None:
        loop = sample_slice.loop
        result.extend(
            [
                Opcode(
                    name='loop_mode',
                    value=(
                        'loop_continuous'
                        if loop.mode == enums.LoopMode.through_release
                        else 'loop_sustain'
                    ),
                ),
                Opcode(name='loop_start', value=str(loop.start_frame)),
                Opcode(name='loop_end', value=str(_inclusive_end(loop.end_frame))),
            ]
        )
        if loop.crossfade_frames:
            _issue(
                issues,
                f'{path}.playback.loop.crossfade_frames',
                loop.crossfade_frames,
                'Loop crossfade frames have no exact implemented SFZ conversion',
            )
    else:
        result.append(
            Opcode(
                name='loop_mode',
                value='one_shot' if mode == enums.PlaybackMode.one_shot else 'no_loop',
            )
        )
    return result


def _processing_opcodes(
    document: InstrumentDocument,
    slot: SampleSlot,
    path: str,
    issues: list[UnimplementedFeature],
) -> list[Opcode]:
    instrument = document.body.instrument.processing
    local = slot.processing
    volume = instrument.volume_db + local.volume_db
    tuning = instrument.tuning_cents + local.tuning_cents
    if slot.mapping.pitch_tracking:
        assert slot.mapping.reference_pitch_hz is not None
        assert (key := _pitch_key(slot.mapping.reference_pitch_hz)) is not None
        reference = 440.0 * 2 ** ((key - 69) / 12)
        tuning += 1200 * math.log2(slot.mapping.reference_pitch_hz / reference)
    elif slot.mapping.reference_pitch_hz is not None:
        _issue(
            issues,
            f'{path}.mapping.reference_pitch_hz',
            slot.mapping.reference_pitch_hz,
            'An untracked SFZ region cannot retain a reference pitch as metadata',
        )
    result: list[Opcode] = []
    if volume:
        result.append(Opcode(name='volume', value=_number_text(volume)))
    if tuning:
        transpose = round(tuning / 100)
        if not -127 <= transpose <= 127:
            _issue(
                issues,
                f'{path}.processing.tuning_cents',
                tuning,
                'Combined tuning exceeds SFZ transpose range',
            )
        else:
            residual = tuning - 100 * transpose
            if transpose:
                result.append(Opcode(name='transpose', value=str(transpose)))
            if residual:
                result.append(Opcode(name='tune', value=_number_text(residual)))
    pan = instrument.pan + local.pan
    balance = instrument.stereo_balance + local.stereo_balance
    if pan and balance:
        _issue(
            issues,
            f'{path}.processing',
            {'pan': pan, 'stereo_balance': balance},
            'One SFZ pan opcode cannot distinguish simultaneous pan and balance',
        )
    elif pan or balance:
        result.append(Opcode(name='pan', value=_number_text(100 * (pan or balance))))
    for i, band in enumerate(local.equalizer):
        _issue(
            issues,
            f'{path}.processing.equalizer[{i}]',
            band,
            'Instrument equalizer bands have no implemented SFZ conversion',
        )
    return result


def _envelope_opcodes(
    document: InstrumentDocument,
    slot: SampleSlot,
    path: str,
    issues: list[UnimplementedFeature],
) -> list[Opcode]:
    value = slot.envelope or document.body.instrument.envelope
    envelope_path = (
        f'{path}.envelope' if slot.envelope is not None else 'body.instrument.envelope'
    )
    segments = value.segments
    representable = (
        value.clock == Clock.seconds
        and value.scope == Scope.voice
        and value.initial == 0
        and value.hold
        and value.retrigger == envelope.Retrigger.current
        and len(segments) == 4
        and len(value.release) == 1
    )
    if representable:
        representable = (
            [s.target for s in segments[:3]] == [0, 1, 1]
            and [s.curve for s in segments] == [0, 0, 0, -5]
            and value.release[0].target == 0
            and value.release[0].curve == -5
        )
    if not representable:
        _issue(
            issues,
            envelope_path,
            value,
            'SFZ requires a seconds-based delay/attack/hold/decay envelope '
            'with linear attack and exponential decay/release',
        )
        return []
    values = dict(
        zip(
            ('ampeg_delay', 'ampeg_attack', 'ampeg_hold', 'ampeg_decay'),
            (float(s.duration) for s in segments),
            strict=True,
        )
    )
    values['ampeg_sustain'] = segments[-1].target * 100
    values['ampeg_release'] = float(value.release[0].duration)
    return [Opcode(name=n, value=_number_text(v)) for n, v in values.items()]


def _modulation_opcodes(
    slot: SampleSlot, path: str, issues: list[UnimplementedFeature]
) -> list[Opcode]:
    supported: list[modulation.Route] = []
    for i, curve in enumerate(slot.modulation.routes):
        if (
            curve.target == modulation.Target(node='processing', parameter='amplitude')
            and any(
                b.id == curve.source and b.kind == 'velocity' for b in slot.bindings
            )
            and curve.operation == modulation.Operation.multiply
            and curve.interpolation == modulation.Interpolation.linear
            and all(_velocity_number(p.input) is not None for p in curve.points)
            and all(0 <= p.amount <= 1 for p in curve.points)
        ):
            supported.append(curve)
        else:
            _issue(
                issues,
                f'{path}.modulation.routes[{i}]',
                curve,
                'Only linear amplitude-by-velocity modulation maps exactly to SFZ',
            )
    if len(supported) > 1:
        for curve in supported:
            _issue(
                issues,
                f'{path}.modulation',
                curve,
                'Multiple amplitude curves cannot share one SFZ amp_veltrack',
            )
        return [Opcode(name='amp_veltrack', value='0')]
    if not supported:
        return [Opcode(name='amp_veltrack', value='0')]
    result = [Opcode(name='amp_veltrack', value='100')]
    for point in supported[0].points:
        velocity = _velocity_number(point.input)
        assert velocity is not None
        result.append(
            Opcode(name=f'amp_velcurve_{velocity}', value=_number_text(point.amount))
        )
    return result


def _crossfade_opcodes(
    slot: SampleSlot, path: str, issues: list[UnimplementedFeature]
) -> list[Opcode]:
    result: list[Opcode] = []
    curves: dict[enums.Input, enums.FadeCurve] = {}
    for i, fade in enumerate(slot.crossfades):
        if not isinstance(fade, crossfade.KeyCrossfade):
            _issue(
                issues,
                f'{path}.crossfades[{i}]',
                fade,
                'Control crossfades require an external SFZ input binding',
            )
            continue
        if fade.input == enums.Input.velocity:
            start = _velocity_number(fade.start)
            end = _velocity_number(fade.end)
            if start is None or end is None:
                _issue(
                    issues,
                    f'{path}.crossfades[{i}]',
                    fade,
                    'SFZ velocity crossfades require integer multiples of 1/127',
                )
                continue
            suffix = 'vel'
        else:
            start, end, suffix = fade.start, fade.end, 'key'
        if fade.input in curves and curves[fade.input] != fade.curve:
            _issue(
                issues,
                f'{path}.crossfades[{i}].curve',
                fade.curve,
                'SFZ permits only one crossfade curve per input in a region',
            )
            continue
        curves[fade.input] = fade.curve
        prefix = 'xfin' if fade.direction == enums.FadeDirection.fade_in else 'xfout'
        result.extend(
            [
                Opcode(name=f'{prefix}_lo{suffix}', value=str(start)),
                Opcode(name=f'{prefix}_hi{suffix}', value=str(end)),
            ]
        )
    for source, curve in curves.items():
        result.append(
            Opcode(
                name=f'xf_{"key" if source == enums.Input.key else "vel"}curve',
                value='gain' if curve == enums.FadeCurve.linear else 'power',
            )
        )
    return result


def _slot_issues(
    slot: SampleSlot, path: str, issues: list[UnimplementedFeature]
) -> None:
    if slot.selection is not None:
        _issue(
            issues,
            f'{path}.selection',
            slot.selection,
            'SFZ alternate-selection behavior is not represented',
        )
    for i, articulation in enumerate(slot.articulations):
        _issue(
            issues,
            f'{path}.articulations[{i}]',
            articulation,
            'Instrument articulations require an external SFZ input binding',
        )
    for name, value in slot.envelopes.items():
        _issue(
            issues,
            f'{path}.envelopes.{name}',
            value,
            'Named instrument envelopes have no implemented SFZ conversion',
        )
    for name, value in slot.lfos.items():
        _issue(
            issues,
            f'{path}.lfos.{name}',
            value,
            'Instrument LFOs have no implemented SFZ conversion',
        )


def _pitch_key(value: float | None) -> int | None:
    if value is None:
        return None
    key = round(69 + 12 * math.log2(value / 440))
    return key if 0 <= key <= 127 else None


def _velocity_number(value: object) -> int | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    scaled = value * 127
    rounded = round(scaled)
    return rounded if math.isclose(scaled, rounded, rel_tol=0, abs_tol=1e-12) else None


def _inclusive_end(value: int) -> int:
    return value - 1


def _number_text(value: object) -> str:
    assert isinstance(value, (int, float)) and not isinstance(value, bool)
    number = float(value)
    if number == 0:
        return '0'
    if number.is_integer():
        return str(int(number))
    return repr(number)


def _safe_sample(value: str) -> bool:
    return _safe_value(value) and not value.startswith('*')


def _safe_value(value: str) -> bool:
    return not any(token in value for token in ('\n', '\r', '//', '/*', '<', '=', '#'))


def _issue(
    issues: list[UnimplementedFeature], path: str, value: object, reason: str
) -> None:
    issue = UnimplementedFeature(
        location=InstrumentLocation(path=path),
        value=_json_value(value),
        reason=reason,
    )
    if issue not in issues:
        issues.append(issue)


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(',', ':'),
        default=_json_default,
    )


def _json_default(value: object) -> object:
    if isinstance(value, base.Model):
        return value.model_dump(mode='json')
    raise TypeError(f'Cannot serialize {type(value).__name__} as JSON')


def _json_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, base.Model):
        return value.model_dump_json(exclude_none=False)
    return _json(value)


def _metadata(
    text: str,
) -> tuple[
    dict[str, object] | None, dict[int, dict[str, object]], list[UnimplementedFeature]
]:
    instrument: dict[str, object] | None = None
    slots: dict[int, dict[str, object]] = {}
    issues: list[UnimplementedFeature] = []
    pending: tuple[dict[str, object], int] | None = None
    region = 0
    for line_number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        match = RECS_METADATA.fullmatch(stripped)
        if stripped.startswith(('// recs:instrument', '// recs:slot')) and not match:
            raise ValueError(f'Malformed recs metadata on line {line_number}')
        if match:
            kind, value = match.groups()
            try:
                data = json.loads(value)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f'Malformed recs {kind} metadata on line {line_number}: {e}'
                ) from None
            if kind == 'instrument':
                if not isinstance(data, dict):
                    raise ValueError('Recs instrument metadata must be a JSON object')
                if data.get('version') != 1:
                    issues.append(
                        UnimplementedFeature(
                            location=SfzLocation(
                                header='recs',
                                opcode='instrument',
                                line=line_number,
                                column=line.index('//') + 1,
                            ),
                            value=str(data.get('version')),
                            reason='Recs SFZ metadata version is not implemented',
                        )
                    )
                    continue
                try:
                    parsed = InstrumentMetadata.model_validate(data)
                except ValidationError as e:
                    raise ValueError(
                        f'Malformed recs instrument metadata: {e}'
                    ) from None
                instrument = parsed.model_dump(exclude={'version'})
            else:
                if not isinstance(data, dict):
                    raise ValueError('Recs slot metadata must be a JSON object')
                try:
                    pending = (
                        SlotMetadata.model_validate(data).model_dump(),
                        line_number,
                    )
                except ValidationError as e:
                    raise ValueError(f'Malformed recs slot metadata: {e}') from None
            continue
        if not stripped or stripped.startswith('//'):
            continue
        if '<region>' in stripped:
            region += stripped.count('<region>')
            if pending is not None:
                slots[region] = pending[0]
                pending = None
        elif pending is not None:
            raise ValueError(
                f'Recs slot metadata on line {pending[1]} must precede a region'
            )
    if pending is not None:
        raise ValueError(f'Recs slot metadata on line {pending[1]} has no region')
    return instrument, slots, issues


def _sfz_issue_position(feature: UnimplementedFeature) -> tuple[int, int]:
    assert isinstance(feature.location, SfzLocation)
    return feature.location.line, feature.location.column


def _parse(text: str) -> tuple[list[ParsedRegion], list[UnimplementedFeature]]:
    unimplemented: list[UnimplementedFeature] = []
    text = BLOCK_COMMENT.sub(_blank_comment, text)
    text = LINE_COMMENT.sub('', text)
    text = _remove_preprocessors(text, unimplemented)

    matches = list(TOKEN.finditer(text))
    if not matches and text.strip():
        raise ValueError('SFZ file contains no headers or opcodes')

    current: str | None = None
    current_line = 0
    default_path = ''
    global_opcodes: list[ParsedOpcode] = []
    master_opcodes: list[ParsedOpcode] = []
    group_opcodes: list[ParsedOpcode] = []
    region_opcodes: list[ParsedOpcode] = []
    regions: list[ParsedRegion] = []

    def finish_region() -> None:
        if current == 'region':
            regions.append(
                ParsedRegion(
                    default_path=default_path,
                    opcodes=[
                        *global_opcodes,
                        *master_opcodes,
                        *group_opcodes,
                        *region_opcodes,
                    ],
                    line=current_line,
                )
            )

    line = 1
    previous = 0
    for i, match in enumerate(matches):
        line += text[previous : match.start()].count('\n')
        previous = match.start()
        column = match.start() - text.rfind('\n', 0, match.start())
        if i == 0 and text[: match.start()].strip():
            raise ValueError('Unexpected text before first SFZ header')
        header, opcode = match.groups()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        if header is not None:
            if text[match.end() : end].strip():
                raise ValueError(f'Unexpected text after <{header}>')
            finish_region()
            current = header.lower()
            current_line = line
            if current not in SUPPORTED_HEADERS:
                unimplemented.append(
                    UnimplementedFeature(
                        location=SfzLocation(
                            header=current,
                            opcode=None,
                            line=line,
                            column=column,
                        ),
                        value=None,
                        reason='SFZ header is not implemented',
                    )
                )
                continue
            if current == 'global':
                global_opcodes = []
                master_opcodes = []
                group_opcodes = []
            elif current == 'master':
                master_opcodes = []
                group_opcodes = []
            elif current == 'group':
                group_opcodes = []
            elif current == 'region':
                region_opcodes = []
            continue

        if current is None:
            raise ValueError(f'SFZ opcode outside a header: {opcode}')
        value = text[match.end() : end].strip()
        name = opcode.lower()
        item = ParsedOpcode(
            header=current,
            opcode=name,
            value=value,
            line=line,
            column=column,
        )
        if current not in SUPPORTED_HEADERS:
            continue
        if not value and not (current == 'control' and name == 'default_path'):
            raise ValueError(f'SFZ opcode has no value: {opcode}')
        canonical = OPCODE_ALIASES.get(name, name)
        supported = canonical in SUPPORTED_OPCODES or AMP_VELOCITY_CURVE.fullmatch(
            canonical
        )
        if current == 'control':
            if name != 'default_path':
                _add_unimplemented(
                    unimplemented, item, 'SFZ control opcode is not implemented'
                )
                continue
            default_path = value
        elif not supported:
            _add_unimplemented(unimplemented, item, 'SFZ opcode is not implemented')
        elif current == 'global':
            global_opcodes.append(item)
        elif current == 'master':
            master_opcodes.append(item)
        elif current == 'group':
            group_opcodes.append(item)
        else:
            region_opcodes.append(item)

    finish_region()
    return regions, unimplemented


def _add_unimplemented(
    features: list[UnimplementedFeature], item: ParsedOpcode, reason: str
) -> None:
    features.append(
        UnimplementedFeature(
            location=SfzLocation(
                header=item.header,
                opcode=item.opcode,
                line=item.line,
                column=item.column,
            ),
            value=item.value,
            reason=reason,
        )
    )


def _blank_comment(match: re.Match[str]) -> str:
    return ''.join('\n' if c == '\n' else ' ' for c in match.group())


def _remove_preprocessors(text: str, unimplemented: list[UnimplementedFeature]) -> str:
    result: list[str] = []
    for line, content in enumerate(text.splitlines(keepends=True), 1):
        stripped = content.lstrip()
        if not stripped.startswith('#'):
            result.append(content)
            continue
        body = stripped[1:].strip()
        directive, separator, value = body.partition(' ')
        opcode = f'#{directive}' if directive else '#'
        if directive == 'include':
            reason = 'Vendor-specific #include preprocessing is not implemented'
        elif directive == 'define':
            reason = 'SFZ 2 #define preprocessing is not implemented'
        else:
            reason = 'SFZ preprocessing directive is not implemented'
        unimplemented.append(
            UnimplementedFeature(
                location=SfzLocation(
                    header='preprocessor',
                    opcode=opcode,
                    line=line,
                    column=len(content) - len(stripped) + 1,
                ),
                value=value.strip() if separator else None,
                reason=reason,
            )
        )
        result.append('\n' if content.endswith('\n') else '')
    return ''.join(result)


def _slot(
    index: int,
    asset_metadata: dict[str, AudioMetadata],
    asset_ids: dict[str, str],
    output_channels: list[str],
    region: ParsedRegion,
    unimplemented: list[UnimplementedFeature],
) -> tuple[SampleSlot, playback.Slice] | None:
    values: dict[str, str] = {}
    declarations: dict[str, ParsedOpcode] = {}
    low_key = 0
    high_key = 127
    pitch_keycenter = 60
    for item in region.opcodes:
        opcode = OPCODE_ALIASES.get(item.opcode, item.opcode)
        value = item.value
        values[opcode] = value
        declarations[opcode] = item
        if opcode == 'key':
            low_key = high_key = pitch_keycenter = _key(value, opcode)
        elif opcode == 'lokey':
            low_key = _key(value, opcode)
        elif opcode == 'hikey':
            high_key = _key(value, opcode)
        elif opcode == 'pitch_keycenter':
            pitch_keycenter = _key(value, opcode)

    if (sample := values.get('sample')) is None:
        raise ValueError(f'Region {index}: sample is required')
    if sample.startswith('*'):
        _add_unimplemented(
            unimplemented,
            declarations['sample'],
            'Generated SFZ samples are not implemented',
        )
        return None

    tracking = _number(values.get('pitch_keytrack', '100'), 'pitch_keytrack')
    if tracking not in (0, 100):
        _add_unimplemented(
            unimplemented,
            declarations['pitch_keytrack'],
            'Partial pitch_keytrack is not implemented',
        )
        tracking = 100
    mapping = playback.Mapping(
        lowest_key=low_key,
        highest_key=high_key,
        reference_pitch_hz=(
            440.0 * 2 ** ((pitch_keycenter - 69) / 12) if tracking else None
        ),
        minimum_velocity=_velocity(values.get('lovel', '0'), 'lovel'),
        maximum_velocity=_velocity(values.get('hivel', '127'), 'hivel'),
        pitch_tracking=bool(tracking),
    )

    sample_path = PurePosixPath(
        region.default_path.replace('\\', '/')
    ) / sample.replace('\\', '/')
    metadata = asset_metadata[str(sample_path)]
    kwargs: dict[str, object] = {
        'id': f'region-{index}',
        'slice': f'slice-{index}',
        'mapping': mapping,
        'channels': _channel_routes(metadata.channels, output_channels),
    }
    if name := values.get('region_label'):
        kwargs['name'] = name
    result = _playback(index, values, declarations, metadata, unimplemented)
    sample_slice = playback.Slice.model_validate(
        dict(
            id=f'slice-{index}',
            asset=asset_ids[str(sample_path)],
            start_frame=result.pop('start_frame', 0),
            end_frame=result.pop('end_frame', metadata.frames),
            loop=result.pop('loop', None),
        )
    )
    kwargs['playback'] = playback.SlotPlayback.model_validate(result)
    if result := _processing(values, declarations, metadata.channels, unimplemented):
        kwargs['processing'] = processing.Processing.model_validate(result)
    kwargs['envelope'] = amplitude_envelope(values)
    if result := _velocity_modulation(values):
        kwargs['modulation'] = modulation.Modulation(
            sources=[
                modulation.Source(id='velocity', scope='voice', minimum=0, maximum=1)
            ],
            parameters=[
                modulation.Parameter(
                    target=result.target,
                    unit=modulation.Unit.ratio,
                    scope=Scope.voice,
                    minimum=0,
                    maximum=1,
                    default=1,
                )
            ],
            routes=[result],
        )
        kwargs['bindings'] = [processing.EventBinding(id='velocity', kind='velocity')]
    if result := _crossfades(values):
        kwargs['crossfades'] = result
    if result := _trigger(values, declarations, unimplemented):
        kwargs['trigger'] = result
    if group := _group(values.get('group')):
        kwargs['choke_group'] = group
    if off_by := _group(values.get('off_by')):
        mode = values.get('off_mode', 'fast')
        if mode not in ('fast', 'normal'):
            raise ValueError(f'Region {index}: unsupported off_mode: {mode}')
        kwargs['chokes'] = [
            selection.Choke(
                group=off_by,
                mode=(
                    enums.ChokeMode.immediate
                    if mode == 'fast'
                    else enums.ChokeMode.release
                ),
            )
        ]
    return SampleSlot.model_validate(kwargs), sample_slice


def _playback(
    index: int,
    values: dict[str, str],
    declarations: dict[str, ParsedOpcode],
    metadata: AudioMetadata,
    unimplemented: list[UnimplementedFeature],
) -> dict[str, object]:
    result: dict[str, object] = {}
    if 'offset' in values:
        result['start_frame'] = _integer(values['offset'], 'offset', minimum=0)
    if 'end' in values:
        end = _integer(values['end'], 'end', minimum=0)
        result['end_frame'] = end + 1

    if (direction := values.get('direction')) is not None:
        if direction not in ('forward', 'reverse'):
            raise ValueError(f'Region {index}: unsupported direction: {direction}')
        result['direction'] = (
            enums.Direction.forward
            if direction == 'forward'
            else enums.Direction.backward
        )

    mode = values.get('loop_mode')
    embedded_loop = metadata.embedded_loop
    if (
        embedded_loop is not None
        and embedded_loop.loop_type
        and (
            mode is None
            or mode.startswith('loop_')
            and ('loop_start' not in values or 'loop_end' not in values)
        )
    ):
        _add_unimplemented(
            unimplemented,
            declarations['sample'],
            f'WAV smpl loop type {embedded_loop.loop_type} is not implemented',
        )
        embedded_loop = None
        if mode is not None:
            mode = 'no_loop'

    if mode is None:
        if not metadata.embedded_loop_known:
            _add_unimplemented(
                unimplemented,
                declarations['sample'],
                'Embedded loop metadata cannot be read from this sample format; '
                'set loop_mode explicitly',
            )
            mode = 'no_loop'
        else:
            mode = 'loop_continuous' if embedded_loop is not None else 'no_loop'
    if mode not in ('no_loop', 'one_shot', 'loop_continuous', 'loop_sustain'):
        raise ValueError(f'Region {index}: unsupported loop_mode: {mode}')
    release_trigger = values.get('trigger') in ('release', 'release_key')
    if release_trigger and mode == 'loop_continuous':
        _add_unimplemented(
            unimplemented,
            declarations.get('loop_mode', declarations['sample']),
            'Release-triggered loop_continuous playback is not implemented',
        )
        mode = 'one_shot'
    if mode == 'one_shot' or release_trigger:
        result['mode'] = enums.PlaybackMode.one_shot
    elif mode.startswith('loop_'):
        start = values.get('loop_start')
        end = values.get('loop_end')
        if start is None and embedded_loop is not None:
            start = str(embedded_loop.start_frame)
        if end is None and embedded_loop is not None:
            end = str(embedded_loop.end_frame - 1)
        if start is None or end is None:
            raise ValueError(
                f'Region {index}: loop_start and loop_end require file metadata '
                'or explicit values'
            )
        result['loop'] = playback.Loop(
            start_frame=_integer(start, 'loop_start', minimum=0),
            end_frame=_integer(end, 'loop_end', minimum=0) + 1,
            mode=(
                enums.LoopMode.through_release
                if mode == 'loop_continuous'
                else enums.LoopMode.until_release
            ),
        )
    start_frame = result.get('start_frame', 0)
    end_frame = result.get('end_frame', metadata.frames)
    assert isinstance(start_frame, int)
    assert isinstance(end_frame, int)
    if start_frame >= metadata.frames:
        raise ValueError(f'Region {index}: offset is beyond the end of the sample')
    if end_frame > metadata.frames:
        raise ValueError(f'Region {index}: end is beyond the end of the sample')
    if loop := result.get('loop'):
        assert isinstance(loop, playback.Loop)
        if loop.start_frame < start_frame or loop.end_frame > end_frame:
            raise ValueError(f'Region {index}: loop is outside the playback interval')
    return result


def _processing(
    values: dict[str, str],
    declarations: dict[str, ParsedOpcode],
    channels: int,
    unimplemented: list[UnimplementedFeature],
) -> dict[str, float]:
    result: dict[str, float] = {}
    if 'volume' in values:
        result['volume_db'] = _number(values['volume'], 'volume')
    tuning = _number(values.get('tune', '0'), 'tune')
    tuning += 100 * _number(values.get('transpose', '0'), 'transpose')
    if tuning:
        result['tuning_cents'] = tuning
    if 'pan' in values:
        pan = _number(values['pan'], 'pan') / 100
        if not -1 <= pan <= 1:
            raise ValueError('pan must be between -100 and 100')
        if channels == 1:
            result['pan'] = pan
        elif channels == 2:
            result['stereo_balance'] = pan
        elif pan:
            _add_unimplemented(
                unimplemented,
                declarations['pan'],
                'Panning multichannel samples is not implemented',
            )
    return result


def _trigger(
    values: dict[str, str],
    declarations: dict[str, ParsedOpcode],
    unimplemented: list[UnimplementedFeature],
) -> enums.TriggerKind | None:
    value = values.get('trigger')
    if value in (None, 'attack'):
        return None
    if value == 'release':
        return enums.TriggerKind.logical_release
    if value == 'release_key':
        return enums.TriggerKind.release
    if value in ('first', 'legato'):
        _add_unimplemented(
            unimplemented,
            declarations['trigger'],
            f'trigger={value} is not implemented',
        )
        return None
    raise ValueError(f'Unsupported SFZ trigger: {value}')


def _velocity_modulation(values: dict[str, str]) -> modulation.Route | None:
    tracking = _number(values.get('amp_veltrack', '100'), 'amp_veltrack')
    if not -100 <= tracking <= 100:
        raise ValueError('amp_veltrack must be between -100 and 100')
    if tracking == 0:
        return None

    specified: dict[int, float] = {}
    for opcode, value in values.items():
        if match := AMP_VELOCITY_CURVE.fullmatch(opcode):
            velocity = int(match.group(1))
            if velocity > 127:
                raise ValueError(f'{opcode} velocity must be between 0 and 127')
            amount = _number(value, opcode)
            if not 0 <= amount <= 1:
                raise ValueError(f'{opcode} must be between 0 and 1')
            specified[velocity] = amount

    if specified:
        specified.setdefault(0, 0.0)
        specified.setdefault(127, 1.0)
        curve = _interpolated_velocity_curve(specified)
    else:
        curve = [(v / 127) ** 2 for v in range(128)]

    proportion = abs(tracking) / 100
    gains = (
        [1 - proportion * (1 - a) for a in curve]
        if tracking > 0
        else [proportion * (1 - a) for a in curve]
    )
    return modulation.Route(
        id='velocity-amplitude',
        source='velocity',
        unit=modulation.Unit.ratio,
        target=modulation.Target(node='processing', parameter='amplitude'),
        operation=modulation.Operation.multiply,
        points=[modulation.Point(input=v / 127, amount=a) for v, a in enumerate(gains)],
    )


def _crossfades(values: dict[str, str]) -> list[crossfade.KeyCrossfade]:
    result: list[crossfade.KeyCrossfade] = []
    for source, suffix in ((enums.Input.key, 'key'), (enums.Input.velocity, 'vel')):
        curve_value = values.get(f'xf_{suffix}curve', 'gain')
        if curve_value not in ('gain', 'power'):
            raise ValueError(f'Unsupported xf_{suffix}curve: {curve_value}')
        curve = (
            enums.FadeCurve.linear
            if curve_value == 'gain'
            else enums.FadeCurve.equal_power
        )
        for direction, prefix in (
            (enums.FadeDirection.fade_in, 'xfin'),
            (enums.FadeDirection.fade_out, 'xfout'),
        ):
            low = values.get(f'{prefix}_lo{suffix}')
            high = values.get(f'{prefix}_hi{suffix}')
            if low is None and high is None:
                continue
            if low is None or high is None:
                raise ValueError(
                    f'{prefix}_lo{suffix} and {prefix}_hi{suffix} are required together'
                )
            start = (
                _key(low, f'{prefix}_lo{suffix}')
                if source == enums.Input.key
                else _velocity(low, f'{prefix}_lo{suffix}')
            )
            end = (
                _key(high, f'{prefix}_hi{suffix}')
                if source == enums.Input.key
                else _velocity(high, f'{prefix}_hi{suffix}')
            )
            result.append(
                crossfade.KeyCrossfade(
                    input=source,
                    direction=direction,
                    start=start,
                    end=end,
                    curve=curve,
                )
            )
    return result


def _interpolated_velocity_curve(points: dict[int, float]) -> list[float]:
    result = [0.0] * 128
    ordered = sorted(points.items())
    pairs = zip(ordered, ordered[1:], strict=False)
    for (start, start_value), (end, end_value) in pairs:
        for velocity in range(start, end + 1):
            fraction = (velocity - start) / (end - start)
            result[velocity] = start_value + fraction * (end_value - start_value)
    return result


def _key(value: str, opcode: str) -> int:
    try:
        key = int(value)
    except ValueError:
        if (match := NOTE.fullmatch(value)) is None:
            raise ValueError(f'Invalid {opcode}: {value}') from None
        name, accidental, octave = match.groups()
        key = 12 * (int(octave) + 1) + NOTES[name.lower()]
        key += {'': 0, '#': 1, 'b': -1}[accidental]
    if not 0 <= key <= 127:
        raise ValueError(f'{opcode} must be between 0 and 127')
    return key


def _velocity(value: str, opcode: str) -> float:
    return _integer(value, opcode, minimum=0, maximum=127) / 127


def _integer(
    value: str, opcode: str, *, minimum: int, maximum: int | None = None
) -> int:
    try:
        result = int(value)
    except ValueError:
        raise ValueError(f'{opcode} must be an integer: {value}') from None
    if result < minimum or maximum is not None and result > maximum:
        limit = (
            f'{minimum} to {maximum}' if maximum is not None else f'at least {minimum}'
        )
        raise ValueError(f'{opcode} must be {limit}')
    return result


def _number(value: str, opcode: str) -> float:
    try:
        return float(value)
    except ValueError:
        raise ValueError(f'{opcode} must be numeric: {value}') from None


def _group(value: str | None) -> str | None:
    if value is None or value == '0':
        return None
    try:
        int(value)
    except ValueError:
        raise ValueError(f'SFZ group must be an integer: {value}') from None
    return f'sfz-group-{value}'


SUPPORTED_HEADERS = {'control', 'global', 'master', 'group', 'region'}
SUPPORTED_OPCODES = {
    'ampeg_attack',
    'ampeg_decay',
    'ampeg_delay',
    'ampeg_hold',
    'ampeg_release',
    'ampeg_sustain',
    'amp_veltrack',
    'direction',
    'end',
    'group',
    'hikey',
    'hivel',
    'key',
    'lokey',
    'loop_end',
    'loop_mode',
    'loop_start',
    'lovel',
    'off_by',
    'off_mode',
    'offset',
    'pan',
    'pitch_keycenter',
    'pitch_keytrack',
    'region_label',
    'sample',
    'transpose',
    'trigger',
    'tune',
    'volume',
    'xf_keycurve',
    'xf_velcurve',
    'xfin_hikey',
    'xfin_hivel',
    'xfin_lokey',
    'xfin_lovel',
    'xfout_hikey',
    'xfout_hivel',
    'xfout_lokey',
    'xfout_lovel',
}
OPCODE_ALIASES = {
    'amp_attack': 'ampeg_attack',
    'amp_decay': 'ampeg_decay',
    'amp_delay': 'ampeg_delay',
    'amp_hold': 'ampeg_hold',
    'amp_release': 'ampeg_release',
    'amp_sustain': 'ampeg_sustain',
    'loopend': 'loop_end',
    'loopmode': 'loop_mode',
    'loopstart': 'loop_start',
}

NOTES = {'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11}
NOTE = re.compile(r'([A-Ga-g])([#b]?)(-?\d+)')
TOKEN = re.compile(r'<([A-Za-z_][A-Za-z0-9_]*)>|([A-Za-z_][A-Za-z0-9_]*)=')
BLOCK_COMMENT = re.compile(r'/\*.*?\*/', re.DOTALL)
LINE_COMMENT = re.compile(r'//.*$', re.MULTILINE)
PREPROCESSOR = re.compile(r'^\s*#', re.MULTILINE)
AMP_VELOCITY_CURVE = re.compile(r'amp_velcurve_(\d+)')
RECS_METADATA = re.compile(r'//\s*recs:(instrument|slot)\s+(\{.*\})')
