"""Compile parsed SFZ regions into a native sample instrument."""

from fractions import Fraction
from pathlib import PurePosixPath
from typing import Literal

from .. import envelope, modulation, segments
from ..assets import AudioDescription, ContentIdentity, RelativeFileLocation
from ..control import Scope
from ..interface import AudioBinding, EventType, Input, Output, PerformanceBinding
from ..samples import controls, crossfade, enums, playback, processing, selection
from ..samples.instrument import (
    AudioAsset,
    SampleInstrument,
    SampleInstrumentScore,
    SampleSettings,
    SampleSlot,
)
from ..samples.metadata import AudioMetadata
from ..streams import AudioType
from ..time import Rate, Timebase
from .model import (
    ParsedOpcode,
    ParsedRegion,
    SfzCompileResult,
    SfzSource,
    UnimplementedFeature,
    _channel_routes,
)
from .parser import (
    NOTE,
    NOTES,
    _add_unimplemented,
    _sfz_issue_position,
    sample_paths,
)
from .registry import AMP_VELOCITY_CURVE, OPCODE_ALIASES


def compile_instrument(
    source: SfzSource,
    *,
    name: str,
    title: str,
    assets: dict[str, AudioMetadata],
    output_timebase: Timebase,
    output_channels: list[str],
    sequence_counter: Literal['reject', 'all_note_ons'] = 'reject',
) -> SfzCompileResult:
    """Build a native document from parsed text and caller-supplied asset facts."""
    if sequence_counter not in ('reject', 'all_note_ons'):
        raise ValueError(f'Unknown SFZ sequence counter rule: {sequence_counter}')
    paths = sample_paths(source)
    if missing := [p for p in paths if p not in assets]:
        raise ValueError(f'Missing audio metadata for SFZ samples: {missing}')
    asset_ids = {p: f'asset-{i}' for i, p in enumerate(paths, 1)}
    native_assets: list[AudioAsset] = []
    clocks = {output_timebase.name: output_timebase}
    for path in paths:
        metadata = assets[path]
        clock = Timebase(
            name=f'native-{metadata.sample_rate}',
            rate=Rate(numerator=metadata.sample_rate),
        )
        if clock.name in clocks and clocks[clock.name] != clock:
            raise ValueError('Output timebase conflicts with a native asset clock')
        clocks[clock.name] = clock
        channels = (
            ['mono']
            if metadata.channels == 1
            else ['left', 'right']
            if metadata.channels == 2
            else [f'channel-{i}' for i in range(1, metadata.channels + 1)]
        )
        native_assets.append(
            AudioAsset(
                name=asset_ids[path],
                location=RelativeFileLocation(path=path),
                encoding=metadata.encoding,
                content=ContentIdentity(
                    byte_length=metadata.byte_length, sha256=metadata.sha256
                ),
                audio=AudioDescription(
                    timebase=clock.name, channels=channels, frames=metadata.frames
                ),
            )
        )
    unimplemented = list(source.unimplemented)
    slots: list[SampleSlot] = []
    slices: list[playback.Slice] = []
    for index, region in enumerate(source.regions, 1):
        if (
            result := _slot(
                index,
                assets,
                asset_ids,
                output_channels,
                region,
                unimplemented,
                sequence_counter,
            )
        ) is not None:
            slot, sample_slice = result
            if metadata := source.slot_metadata.get(index):
                slot = SampleSlot.model_validate(slot.model_dump() | metadata)
            slots.append(slot)
            slices.append(sample_slice)
    document = None
    if slots:
        document = SampleInstrumentScore.model_validate(
            dict(
                name=name,
                title=title,
                timebases=list(clocks.values()),
                assets=native_assets,
                inputs=[
                    Input(
                        name='performance',
                        stream=EventType(
                            timebase=output_timebase.name,
                            kinds=['trigger', 'release', 'control_change'],
                        ),
                        binding=PerformanceBinding(),
                    )
                ],
                outputs=[
                    Output(
                        name='audio',
                        stream=AudioType(
                            timebase=output_timebase.name, channels=output_channels
                        ),
                        binding=AudioBinding(),
                    )
                ],
                body=SampleInstrument(
                    settings=SampleSettings(
                        controls={'sustain': controls.ControlDeclaration()},
                        sustain=selection.Sustain(control='sustain'),
                    ),
                    slots=slots,
                    slices=slices,
                ),
            )
            | source.instrument_metadata
        )
    unimplemented.sort(key=_sfz_issue_position)
    return SfzCompileResult(instrument=document, unimplemented=unimplemented)


def amplitude_envelope(values: dict[str, str]) -> envelope.Envelope:
    """Translate SFZ's DAHDSR vocabulary into the one shared segment model."""
    durations = [
        Fraction(values.get(f'ampeg_{n}', '0'))
        for n in ('delay', 'attack', 'hold', 'decay')
    ]
    sustain = _number(values.get('ampeg_sustain', '100'), 'ampeg_sustain') / 100
    return envelope.Envelope(
        segments=[
            segments.Segment(duration=d, to=t, curve=c)
            for d, t, c in zip(
                durations, [0, 1, 1, sustain], [0, 0, 0, -5], strict=True
            )
        ],
        release=[
            segments.Segment(
                duration=Fraction(values.get('ampeg_release', '0.001')),
                to=0,
                curve=-5,
            )
        ],
    )


def _slot(
    index: int,
    asset_metadata: dict[str, AudioMetadata],
    asset_ids: dict[str, str],
    output_channels: list[str],
    region: ParsedRegion,
    unimplemented: list[UnimplementedFeature],
    sequence_counter: Literal['reject', 'all_note_ons'],
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

    tracking = _integer(
        values.get('pitch_keytrack', '100'),
        'pitch_keytrack',
        minimum=-1200,
        maximum=1200,
    )
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
        'name': f'region-{index}',
        'slice': f'slice-{index}',
        'mapping': mapping,
        'channels': _channel_routes(metadata.channels, output_channels),
    }
    if 'seq_length' in values or 'seq_position' in values:
        if sequence_counter == 'reject':
            for name in ('seq_length', 'seq_position'):
                if name in declarations:
                    _add_unimplemented(
                        unimplemented,
                        declarations[name],
                        'SFZ sequence requires an explicit counter rule',
                    )
        else:
            length = _integer(
                values.get('seq_length', '1'), 'seq_length', minimum=1, maximum=100
            )
            position = _integer(
                values.get('seq_position', '1'),
                'seq_position',
                minimum=1,
                maximum=100,
            )
            kwargs['sequence'] = selection.SequencePosition(
                length=length, position=position
            )
    if 'lorand' in values or 'hirand' in values:
        kwargs['random_range'] = selection.RandomRange(
            minimum=_number(values.get('lorand', '0'), 'lorand'),
            maximum=_number(values.get('hirand', '1'), 'hirand'),
        )
    if name := values.get('region_label'):
        kwargs['title'] = name
    result = _playback(index, values, declarations, metadata, unimplemented)
    sample_slice = playback.Slice.model_validate(
        dict(
            name=f'slice-{index}',
            asset=asset_ids[str(sample_path)],
            start_frame=result.pop('start_frame', 0),
            end_frame=result.pop('end_frame', metadata.frames),
            loop=result.pop('loop', None),
        )
    )
    kwargs['playback'] = playback.SlotPlayback.model_validate(result)
    processing_values = _processing(
        values, declarations, metadata.channels, unimplemented
    )
    slot_processing = processing.Processing.model_validate(processing_values)
    if processing_values:
        kwargs['processing'] = slot_processing
    slot_envelope = amplitude_envelope(values)
    kwargs['envelope'] = slot_envelope
    sources: list[modulation.Source] = []
    parameters: list[modulation.Parameter] = []
    routes: list[modulation.Route] = []
    bindings: list[processing.EventBinding] = []
    if result := _velocity_modulation(values):
        sources.append(
            modulation.Source(name='velocity', scope='voice', minimum=0, maximum=1)
        )
        parameters.append(
            modulation.Parameter(
                target=result.target,
                unit=modulation.Unit.ratio,
                scope=Scope.voice,
                minimum=0,
                maximum=1,
                default=1,
            )
        )
        routes.append(result)
        bindings.append(processing.EventBinding(name='velocity', kind='velocity'))
    pitch_velocity = _velocity_pitch_modulation(values)
    if pitch_velocity is not None:
        if not any(s.name == 'velocity' for s in sources):
            sources.append(
                modulation.Source(name='velocity', scope='voice', minimum=0, maximum=1)
            )
            bindings.append(processing.EventBinding(name='velocity', kind='velocity'))
        routes.append(pitch_velocity)
    for parameter_name, base, amount in _velocity_envelope_durations(
        values, slot_envelope
    ):
        if not any(source.name == 'velocity' for source in sources):
            sources.append(
                modulation.Source(name='velocity', scope='voice', minimum=0, maximum=1)
            )
            bindings.append(processing.EventBinding(name='velocity', kind='velocity'))
        target = modulation.Target(name='envelope', parameter=parameter_name)
        parameters.append(
            modulation.Parameter(
                target=target,
                unit=modulation.Unit.seconds,
                scope=Scope.voice,
                minimum=min(base, base + amount),
                maximum=max(base, base + amount),
                default=base,
            )
        )
        routes.append(
            modulation.Route(
                name=f'velocity-{parameter_name}',
                source='velocity',
                target=target,
                operation=modulation.Operation.add,
                unit=modulation.Unit.seconds,
                points=[
                    modulation.Point(input=0, amount=0),
                    modulation.Point(input=1, amount=amount),
                ],
            )
        )
    key_routes = [
        r
        for r in (
            _key_amplitude_modulation(values),
            _key_pitch_modulation(tracking, pitch_keycenter),
        )
        if r is not None
    ]
    if key_routes:
        sources.append(
            modulation.Source(name='key', scope='voice', minimum=0, maximum=127)
        )
        for route in key_routes:
            if route.target.parameter == 'tuning_cents':
                routes.append(route)
                continue
            base = getattr(slot_processing, route.target.parameter)
            amounts = [p.amount for p in route.points]
            parameters.append(
                modulation.Parameter(
                    target=route.target,
                    unit=route.unit,
                    scope=Scope.voice,
                    minimum=base + min(0, *amounts),
                    maximum=base + max(0, *amounts),
                    default=base,
                )
            )
            routes.append(route)
        bindings.append(processing.EventBinding(name='key', kind='key'))
    pitch_key = next(
        (r for r in key_routes if r.target.parameter == 'tuning_cents'), None
    )
    if pitch_key is not None or pitch_velocity is not None:
        base = slot_processing.tuning_cents
        pitch_routes = [r for r in (pitch_key, pitch_velocity) if r is not None]
        lower = sum(min(0, *(p.amount for p in r.points)) for r in pitch_routes)
        upper = sum(max(0, *(p.amount for p in r.points)) for r in pitch_routes)
        parameters.append(
            modulation.Parameter(
                target=modulation.Target(name='processing', parameter='tuning_cents'),
                unit=modulation.Unit.cents,
                scope=Scope.voice,
                minimum=base + lower,
                maximum=base + upper,
                default=base,
            )
        )
    if routes:
        kwargs['modulation'] = modulation.Modulation(
            sources=sources, parameters=parameters, routes=routes
        )
        kwargs['bindings'] = bindings
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
    if 'count' in values:
        count = _integer(values['count'], 'count', minimum=0, maximum=2**32)
        if count == 0:
            _add_unimplemented(
                unimplemented,
                declarations['count'],
                'SFZ count=0 differs between players',
            )
        else:
            result['play_count'] = count
            mode = 'one_shot'
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
            repeat_count=(
                _integer(values['loop_count'], 'loop_count', minimum=0)
                if 'loop_count' in values
                else None
            ),
        )
    elif 'loop_count' in values:
        _add_unimplemented(
            unimplemented,
            declarations['loop_count'],
            'SFZ loop_count requires an active loop',
        )
    if 'delay' in values:
        delay = _number(values['delay'], 'delay')
        if not 0 <= delay <= 100:
            raise ValueError('delay must be between 0 and 100 seconds')
        if (
            delay
            and not release_trigger
            and result.get('mode') == enums.PlaybackMode.one_shot
        ):
            _add_unimplemented(
                unimplemented,
                declarations['delay'],
                'SFZ one-shot delayed note-off behavior differs between players',
            )
        else:
            result['start_delay_seconds'] = delay
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
        name='velocity-amplitude',
        source='velocity',
        unit=modulation.Unit.ratio,
        target=modulation.Target(name='processing', parameter='amplitude'),
        operation=modulation.Operation.multiply,
        points=[modulation.Point(input=v / 127, amount=a) for v, a in enumerate(gains)],
    )


def _key_amplitude_modulation(values: dict[str, str]) -> modulation.Route | None:
    center = _key(values.get('amp_keycenter', '60'), 'amp_keycenter')
    tracking = _number(values.get('amp_keytrack', '0'), 'amp_keytrack')
    if not -96 <= tracking <= 12:
        raise ValueError('amp_keytrack must be between -96 and 12')
    if not tracking:
        return None
    return modulation.Route(
        name='key-amplitude',
        source='key',
        target=modulation.Target(name='processing', parameter='volume_db'),
        operation=modulation.Operation.add,
        unit=modulation.Unit.db,
        points=[
            modulation.Point(input=key, amount=(key - center) * tracking)
            for key in (0, 127)
        ],
    )


def _key_pitch_modulation(tracking: int, center: int) -> modulation.Route | None:
    if tracking in (0, 100):
        return None
    return modulation.Route(
        name='key-pitch',
        source='key',
        target=modulation.Target(name='processing', parameter='tuning_cents'),
        operation=modulation.Operation.add,
        unit=modulation.Unit.cents,
        points=[
            modulation.Point(input=key, amount=(key - center) * (tracking - 100))
            for key in (0, 127)
        ],
    )


def _velocity_pitch_modulation(values: dict[str, str]) -> modulation.Route | None:
    tracking = _integer(
        values.get('pitch_veltrack', '0'),
        'pitch_veltrack',
        minimum=-9600,
        maximum=9600,
    )
    if not tracking:
        return None
    return modulation.Route(
        name='velocity-pitch',
        source='velocity',
        target=modulation.Target(name='processing', parameter='tuning_cents'),
        operation=modulation.Operation.add,
        unit=modulation.Unit.cents,
        points=[
            modulation.Point(input=0, amount=0),
            modulation.Point(input=1, amount=tracking),
        ],
    )


def _velocity_envelope_durations(
    values: dict[str, str], definition: envelope.Envelope
) -> list[tuple[str, float, float]]:
    result: list[tuple[str, float, float]] = []
    for name, phase, index in (
        ('delay', 'on', 0),
        ('attack', 'on', 1),
        ('hold', 'on', 2),
        ('decay', 'on', 3),
        ('release', 'release', 0),
    ):
        opcode = f'ampeg_vel2{name}'
        if opcode not in values:
            continue
        segments = definition.segments if phase == 'on' else definition.release
        base = float(segments[index].duration)
        amount = _number(values[opcode], opcode)
        if not -100 <= amount <= 100:
            raise ValueError(f'{opcode} must be between -100 and 100')
        if base + amount < 0:
            raise ValueError(f'{opcode} makes envelope duration negative')
        result.append((f'{phase}-{index}-duration', base, amount))
    return result


def _crossfades(values: dict[str, str]) -> list[crossfade.KeyCrossfade]:
    result: list[crossfade.KeyCrossfade] = []
    for source, suffix in (
        (enums.CrossfadeInput.key, 'key'),
        (enums.CrossfadeInput.velocity, 'vel'),
    ):
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
                if source == enums.CrossfadeInput.key
                else _velocity(low, f'{prefix}_lo{suffix}')
            )
            end = (
                _key(high, f'{prefix}_hi{suffix}')
                if source == enums.CrossfadeInput.key
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
