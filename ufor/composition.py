"""Resolve supplied scores into independent parts, without I/O or audio."""

from fractions import Fraction
from typing import Self

from pydantic import Field, model_validator

from . import light_animation
from .arrangement import ArrangementScore
from .base import Model
from .codec import ScoreValue
from .events import ControlChange, Release, StoredEvent, Trigger
from .interface import (
    EventType,
    Input,
    InputSelection,
    InterfaceScore,
    MixBinding,
    Output,
    OutputSelection,
    ParameterExport,
    SequenceBinding,
    StreamBinding,
)
from .light_animation import AnimationScore
from .lights import LightType
from .modulation import Unit
from .recording import AudioStream, RecordingScore
from .samples.enums import SelectionMode
from .samples.instrument import InstrumentScore
from .sequence import SequenceScore
from .streams import AudioType


class ScoreRecord(Model):
    score: ScoreValue
    paths: dict[str, str] = Field(default_factory=dict)
    sha256: str | None = None


class ParameterContract(Model):
    unit: Unit
    minimum: float
    maximum: float
    default: float

    @model_validator(mode='after')
    def valid_default(self) -> Self:
        if not self.minimum <= self.default <= self.maximum:
            raise ValueError('parameter default is outside its effective range')
        return self


class PreparedPart(Model):
    score: str
    parameters: dict[str, float]
    children: dict[str, str] = Field(default_factory=dict)


class EventDelivery(Model):
    part: str
    input: str
    event: StoredEvent


class Composition:
    def __init__(
        self,
        root: str,
        scores: dict[str, ScoreRecord],
        parameters: dict[str, float] | None = None,
    ) -> None:
        self.scores = scores
        self.parts: dict[str, PreparedPart] = {}
        self.root = root
        self._check_definitions(root, [], {})
        self._instantiate(root, 'root', parameters or {})
        self._validate_instances()

    def parameter_contract(self, identity: str, name: str) -> ParameterContract:
        score = self.scores[identity].score
        if not isinstance(score, InterfaceScore):
            raise ValueError(f'{identity}: no public interface')
        export = next((p for p in score.parameters if p.name == name), None)
        if export is None:
            raise ValueError(f'{identity}: unknown public parameter {name}')
        if isinstance(score, (ArrangementScore, AnimationScore)) and (
            not isinstance(score, AnimationScore) or export.binding.name != 'animation'
        ):
            child_part = next(
                n for n in score.body.parts if n.name == export.binding.name
            )
            child = self.scores[identity].paths[child_part.score.key]
            inherited = self.parameter_contract(child, export.binding.parameter)
            inherited = inherited.model_copy(
                update={
                    'default': child_part.parameters.get(
                        export.binding.parameter, inherited.default
                    )
                }
            )
        elif isinstance(score, (InstrumentScore, AnimationScore)):
            internal = next(
                (
                    p
                    for p in (
                        score.body.instrument.modulation.parameters
                        if isinstance(score, InstrumentScore)
                        else score.body.modulation.parameters
                    )
                    if p.target == export.binding
                ),
                None,
            )
            if internal is None:
                raise ValueError(
                    f'{identity}: exported parameter requires '
                    'a declared internal parameter'
                )
            inherited = ParameterContract(
                unit=internal.unit,
                minimum=internal.minimum,
                maximum=internal.maximum,
                default=internal.default,
            )
        else:
            raise ValueError(f'{identity}: unsupported configurable score')
        return _narrow(inherited, export)

    def output(self, part: str, name: str) -> Output:
        score = self.scores[self.parts[part].score].score
        if isinstance(score, InterfaceScore):
            for output in score.outputs:
                if output.name == name:
                    return output
        raise ValueError(f'{part}: unknown public output {name}')

    def input(self, part: str, name: str) -> Input:
        score = self.scores[self.parts[part].score].score
        if isinstance(score, InterfaceScore):
            for input in score.inputs:
                if input.name == name:
                    return input
        raise ValueError(f'{part}: unknown public input {name}')

    def rate(self, part: str, timebase: str) -> Fraction:
        score = self.scores[self.parts[part].score].score
        if not isinstance(score, InterfaceScore):
            raise ValueError('score has no timebases')
        clock = next(t for t in score.timebases if t.name == timebase)
        return Fraction(clock.rate.numerator, clock.rate.denominator)

    def extent(self, part: str, port_name: str) -> tuple[int, int | None]:
        port = self.output(part, port_name)
        score = self.scores[self.parts[part].score].score
        binding = port.binding
        if isinstance(binding, OutputSelection):
            child = self.parts[part].children[binding.name]
            start, end = self.extent(child, binding.output)
            rate = self.rate(part, port.stream.timebase) / self.rate(
                child, self.output(child, binding.output).stream.timebase
            )
            return exact_tick(start, rate), None if end is None else exact_tick(
                end, rate
            )
        if isinstance(score, AnimationScore) and isinstance(
            score.body.operation, light_animation.Cues
        ):
            cue = score.body.operation.cues[-1]
            return 0, int(
                (cue.start + cue.duration) * self.rate(part, port.stream.timebase)
            )
        if isinstance(score, AnimationScore):
            extents = [
                self.extent(self.parts[part].children[s.name], s.output)
                for s in light_animation.sources(score.body.operation)
            ]
            ends = [e for _, e in extents if e is not None]
            return max((s for s, _ in extents), default=0), min(ends) if ends else None
        if isinstance(score, SequenceScore):
            return score.body.start, score.body.end
        if isinstance(score, RecordingScore) and isinstance(binding, StreamBinding):
            stream = next(s for s in score.body.streams if s.name == binding.stream)
            if isinstance(stream, AudioStream):
                return 0, stream.end
            starts = [f.start for f in stream.fragments if f.start is not None]
            ends = [f.end for f in stream.fragments if f.end is not None]
            return min(starts, default=0), max(ends, default=0)
        if isinstance(score, ArrangementScore) and isinstance(binding, MixBinding):
            extents = {
                t.name: max(
                    (
                        c.timeline_start + c.source_end - c.source_start
                        for c in score.body.clips
                        if c.track == t.name
                    ),
                    default=0,
                )
                for t in score.body.tracks
            }
            for bus in score.body.bus_order:
                extents[bus] = max(
                    (
                        extents[r.source]
                        for r in score.body.routes
                        if r.destination == bus
                    ),
                    default=0,
                )
            return (
                binding.start or 0,
                binding.end
                if binding.end is not None
                else extents[str(binding.track or binding.bus)],
            )
        return 0, None

    def events(self, part: str, port_name: str) -> list[StoredEvent] | None:
        port = self.output(part, port_name)
        score = self.scores[self.parts[part].score].score
        if isinstance(score, SequenceScore) and isinstance(
            port.binding, SequenceBinding
        ):
            return list(score.body.events)
        if isinstance(port.binding, OutputSelection):
            child = self.parts[part].children[port.binding.name]
            events = self.events(child, port.binding.output)
            if events is None:
                return None
            ratio = self.rate(part, port.stream.timebase) / self.rate(
                child, self.output(child, port.binding.output).stream.timebase
            )
            return [
                e.model_copy(update={'tick': exact_tick(e.tick, ratio)}) for e in events
            ]
        return None

    def evaluation_windows(
        self, start: int, end: int, outputs: list[str] | None = None
    ) -> dict[tuple[str, str], tuple[int, int]]:
        """Propagate output requests through clips; windows retain native positions."""
        if not 0 <= start < end:
            raise ValueError('evaluation requires a nonempty nonnegative interval')
        score = self.scores[self.root].score
        if not isinstance(score, InterfaceScore):
            raise ValueError('root has no interface')
        requests: dict[tuple[str, str], tuple[int, int]] = {}
        for name in outputs if outputs is not None else [p.name for p in score.outputs]:
            self._request('root', name, start, end, requests)
        return requests

    def performance_trace(
        self, end: int, start: int = 0, outputs: list[str] | None = None
    ) -> list[EventDelivery]:
        """Replay instrument histories with pre-roll, without generating audio."""
        windows = self.evaluation_windows(start, end, outputs)
        deliveries: list[EventDelivery] = []
        for (path, port_name), (_, stop) in windows.items():
            score = self.scores[self.parts[path].score].score
            if not isinstance(score, InstrumentScore):
                continue
            if any(
                s.mode in (SelectionMode.random, SelectionMode.shuffle)
                for s in score.body.instrument.selections
            ):
                raise ValueError(
                    f'{path}: deterministic selection execution is not defined'
                )
            output = self.output(path, port_name)
            for port in score.inputs:
                source, source_port = self._input_source(path, port.name)
                events = self.events(source, source_port)
                if events is None:
                    raise ValueError(
                        f'{source}: event payload requires a host provider'
                    )
                self._deliver(
                    path,
                    port.name,
                    events,
                    self.rate(source, self.output(source, source_port).stream.timebase),
                    Fraction(stop, 1) / self.rate(path, output.stream.timebase),
                    deliveries,
                )
        return sorted(
            deliveries,
            key=lambda d: (
                Fraction(d.event.tick, 1)
                / self.rate(d.part, self.input(d.part, d.input).stream.timebase),
                d.event.ordinal,
                d.part,
                d.input,
            ),
        )

    def _input_source(self, path: str, port_name: str) -> tuple[str, str]:
        if path == 'root':
            raise ValueError('offline evaluation requires supplied root input events')
        parent, child_part = path.rsplit('/', 1)
        part = self.parts[parent]
        score = self.scores[part.score].score
        assert isinstance(score, ArrangementScore)
        address = InputSelection(name=child_part, input=port_name)
        for edge in score.body.connections:
            if edge.destination == address:
                return part.children[edge.source.name], edge.source.output
        for port in score.inputs:
            if port.binding == address:
                return self._input_source(parent, port.name)
        raise ValueError(f'{path}.{port_name}: required input is not supplied')

    def _request(
        self,
        path: str,
        name: str,
        start: int,
        end: int,
        requests: dict[tuple[str, str], tuple[int, int]],
    ) -> None:
        port = self.output(path, name)
        low, high = self.extent(path, name)
        if start < low or high is not None and end > high:
            raise ValueError(f'{path}.{name}: request exceeds output extent')
        key = path, name
        previous = requests.get(key)
        requests[key] = (
            (min(start, previous[0]), max(end, previous[1]))
            if previous
            else (start, end)
        )
        score = self.scores[self.parts[path].score].score
        binding = port.binding
        if isinstance(binding, OutputSelection):
            child = self.parts[path].children[binding.name]
            ratio = self.rate(
                child, self.output(child, binding.output).stream.timebase
            ) / self.rate(path, port.stream.timebase)
            self._request(
                child,
                binding.output,
                exact_tick(start, ratio),
                exact_tick(end, ratio),
                requests,
            )
        elif isinstance(score, AnimationScore):
            operation = score.body.operation
            rate = self.rate(path, port.stream.timebase)
            if isinstance(operation, light_animation.Cues):
                for cue in operation.cues:
                    lo = max(start, int(cue.start * rate))
                    hi = min(end, int((cue.start + cue.duration) * rate))
                    if lo < hi:
                        self._request(
                            self.parts[path].children[cue.source.name],
                            cue.source.output,
                            0,
                            hi - int(cue.start * rate),
                            requests,
                        )
            else:
                for selection in light_animation.sources(operation):
                    self._request(
                        self.parts[path].children[selection.name],
                        selection.output,
                        0,
                        end,
                        requests,
                    )
        elif isinstance(score, ArrangementScore) and isinstance(binding, MixBinding):
            relevant = {binding.track or binding.bus}
            for bus in reversed(score.body.bus_order):
                if bus in relevant:
                    relevant.update(
                        r.source for r in score.body.routes if r.destination == bus
                    )
            for clip in score.body.clips:
                if clip.track not in relevant:
                    continue
                lo = max(start, clip.timeline_start)
                hi = min(end, clip.timeline_start + clip.source_end - clip.source_start)
                if lo < hi:
                    self._request(
                        self.parts[path].children[clip.source.name],
                        clip.source.output,
                        clip.source_start + lo - clip.timeline_start,
                        clip.source_start + hi - clip.timeline_start,
                        requests,
                    )

    def _deliver(
        self,
        target: str,
        name: str,
        events: list[StoredEvent],
        source_rate: Fraction,
        end: Fraction,
        result: list[EventDelivery],
    ) -> None:
        port = self.input(target, name)
        rate = self.rate(target, port.stream.timebase)
        converted = [
            e.model_copy(update={'tick': exact_tick(e.tick, rate / source_rate)})
            for e in events
        ]
        if isinstance(port.binding, InputSelection):
            self._deliver(
                self.parts[target].children[port.binding.name],
                port.binding.input,
                converted,
                rate,
                end,
                result,
            )
            return
        score = self.scores[self.parts[target].score].score
        if not isinstance(score, InstrumentScore):
            raise ValueError(f'{target}: no performance consumer')
        for event in converted:
            if event.tick < 0:
                raise ValueError('negative performance positions are unsupported')
            if not isinstance(event, (Trigger, Release, ControlChange)):
                raise ValueError('instrument accepts only performance events')
            score.body.validate_event(event)
            if (
                isinstance(event, Trigger)
                and event.pitch_hz is None
                and any(
                    s.mapping.pitch_tracking
                    and s.mapping.lowest_key <= event.key <= s.mapping.highest_key
                    and s.mapping.minimum_velocity
                    <= event.velocity
                    <= s.mapping.maximum_velocity
                    for s in score.body.slots
                )
            ):
                raise ValueError(f'{target}: pitch-tracked trigger requires pitch_hz')
            if Fraction(event.tick, 1) / rate < end:
                result.append(EventDelivery(part=target, input=name, event=event))

    def _check_definitions(
        self, identity: str, stack: list[str], pins: dict[str, str]
    ) -> None:
        if identity in stack:
            raise ValueError(f'ScoreVersion cycle: {stack + [identity]}')
        if identity not in self.scores:
            raise ValueError(f'Missing score: {identity}')
        record = self.scores[identity]
        score = record.score
        if not isinstance(score, (ArrangementScore, AnimationScore)):
            return
        for child_part in score.body.parts:
            reference = child_part.score
            child = record.paths.get(reference.key)
            if child is None or child not in self.scores:
                raise ValueError(
                    f'{identity}/{child_part.name}: missing score {reference.key}'
                )
            if reference.sha256 is not None:
                if child in pins and pins[child] != reference.sha256:
                    raise ValueError(f'Contradictory score pins: {child}')
                pins[child] = reference.sha256
                if self.scores[child].sha256 != reference.sha256:
                    raise ValueError(f'ScoreVersion digest mismatch: {child}')
            self._check_definitions(child, stack + [identity], pins)

    def _instantiate(self, identity: str, path: str, values: dict[str, float]) -> None:
        score = self.scores[identity].score
        if not isinstance(score, InterfaceScore):
            raise ValueError(f'{path}: score cannot be instantiated')
        contracts = {
            p.name: self.parameter_contract(identity, p.name) for p in score.parameters
        }
        if unknown := values.keys() - contracts.keys():
            raise ValueError(f'{path}: unknown public parameters {sorted(unknown)}')
        configured = {k: values.get(k, v.default) for k, v in contracts.items()}
        for name, value in configured.items():
            if not contracts[name].minimum <= value <= contracts[name].maximum:
                raise ValueError(f'{path}/{name}: parameter outside public range')
        children = {}
        if isinstance(score, (ArrangementScore, AnimationScore)):
            for child_part in score.body.parts:
                child_values = dict(child_part.parameters)
                for export in score.parameters:
                    if export.binding.name == child_part.name:
                        child_values[export.binding.parameter] = configured[export.name]
                child = self.scores[identity].paths[child_part.score.key]
                child_path = f'{path}/{child_part.name}'
                children[child_part.name] = child_path
                self._instantiate(child, child_path, child_values)
        self.parts[path] = PreparedPart(
            score=identity, parameters=configured, children=children
        )

    def _compatible(
        self,
        source: str,
        output: str,
        target: str,
        input_name: str,
        forwarded: str | None = None,
    ) -> None:
        left = (
            self.input(source, output)
            if forwarded == 'input'
            else self.output(source, output)
        )
        right = (
            self.output(target, input_name)
            if forwarded == 'output'
            else self.input(target, input_name)
        )
        a, b = left.stream, right.stream
        ratio = self.rate(target, b.timebase) / self.rate(source, a.timebase)
        if isinstance(a, AudioType) and isinstance(b, AudioType):
            valid = ratio == 1 and a.channels == b.channels
        elif isinstance(a, LightType) and isinstance(b, LightType):
            valid = ratio == 1 and a.model_dump(exclude={'timebase'}) == b.model_dump(
                exclude={'timebase'}
            )
        elif isinstance(a, EventType) and isinstance(b, EventType):
            valid = set(a.kinds) <= set(b.kinds)
            events = None if forwarded == 'input' else self.events(source, output)
            if events is not None:
                for event in events:
                    exact_tick(event.tick, ratio)
            elif ratio.denominator != 1:
                raise ValueError(
                    'exact event-clock conversion requires payload positions'
                )
        else:
            valid = False
        if not valid:
            raise ValueError(
                f'{source}.{output} -> {target}.{input_name}: '
                f'incompatible contracts {a} / {b}'
            )

    def _validate_instances(self) -> None:
        for path, part in self.parts.items():
            score = self.scores[part.score].score
            if isinstance(score, AnimationScore):
                selected = {}
                for selection in light_animation.sources(score.body.operation):
                    child = part.children[selection.name]
                    output = self.output(child, selection.output)
                    if not isinstance(output.stream, LightType):
                        raise ValueError('light operation requires a light source')
                    if self.rate(child, output.stream.timebase) != self.rate(
                        path, score.outputs[0].stream.timebase
                    ):
                        raise ValueError(
                            'light sources must share the logical update rate'
                        )
                    selected[selection] = output.stream
                light_animation.validate_sources(score, selected)
                if isinstance(score.body.operation, light_animation.Cues):
                    rate = self.rate(path, score.outputs[0].stream.timebase)
                    for cue in score.body.operation.cues:
                        low, high = self.extent(
                            part.children[cue.source.name], cue.source.output
                        )
                        if low > 0 or high is not None and cue.duration * rate > high:
                            raise ValueError('cue duration exceeds its source extent')
                continue
            if not isinstance(score, ArrangementScore):
                continue
            supplied = {c.destination for c in score.body.connections}
            for port in score.inputs:
                if isinstance(port.binding, InputSelection):
                    child = part.children[port.binding.name]
                    supplied.add(port.binding)
                    self._compatible(
                        path, port.name, child, port.binding.input, 'input'
                    )
            for port in score.outputs:
                if isinstance(port.binding, OutputSelection):
                    child = part.children[port.binding.name]
                    self._compatible(
                        child, port.binding.output, path, port.name, 'output'
                    )
            for edge in score.body.connections:
                self._compatible(
                    part.children[edge.source.name],
                    edge.source.output,
                    part.children[edge.destination.name],
                    edge.destination.input,
                )
            for child_part, child in part.children.items():
                child_doc = self.scores[self.parts[child].score].score
                if isinstance(child_doc, InterfaceScore):
                    for port in child_doc.inputs:
                        if (
                            InputSelection(name=child_part, input=port.name)
                            not in supplied
                        ):
                            raise ValueError(
                                f'{child}.{port.name}: required input is not supplied'
                            )
            for edge in score.body.connections:
                source = part.children[edge.source.name]
                if not isinstance(
                    self.output(source, edge.source.output).stream, EventType
                ):
                    continue
                events = self.events(source, edge.source.output)
                if events is not None:
                    self._deliver(
                        part.children[edge.destination.name],
                        edge.destination.input,
                        events,
                        self.rate(
                            source,
                            self.output(source, edge.source.output).stream.timebase,
                        ),
                        Fraction(0),
                        [],
                    )
            tracks = {t.name: t.stream for t in score.body.tracks}
            for clip in score.body.clips:
                child = part.children[clip.source.name]
                port = self.output(child, clip.source.output)
                stream = tracks[clip.track]
                if (
                    not isinstance(port.stream, AudioType)
                    or port.stream.channels != stream.channels
                    or self.rate(child, port.stream.timebase)
                    != self.rate(path, stream.timebase)
                ):
                    raise ValueError(f'{path}/{clip.name}: incompatible clip source')
                start, end = self.extent(child, port.name)
                if (
                    clip.source_start < start
                    or end is not None
                    and clip.source_end > end
                ):
                    raise ValueError(f'{path}/{clip.name}: clip exceeds source extent')


def exact_tick(tick: int, ratio: Fraction) -> int:
    value = tick * ratio
    if value.denominator != 1:
        raise ValueError(f'event position {value} is not an exact integer tick')
    return value.numerator


def _narrow(inherited: ParameterContract, export: ParameterExport) -> ParameterContract:
    minimum = inherited.minimum if export.minimum is None else export.minimum
    maximum = inherited.maximum if export.maximum is None else export.maximum
    if minimum < inherited.minimum or maximum > inherited.maximum:
        raise ValueError('public parameter cannot widen the internal range')
    return ParameterContract(
        unit=inherited.unit,
        minimum=minimum,
        maximum=maximum,
        default=inherited.default if export.default is None else export.default,
    )
