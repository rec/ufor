"""Resolve supplied definitions into independent instances, without I/O or audio."""

from fractions import Fraction
from typing import Self

from pydantic import Field, model_validator

from .arrangement import ArrangementDocument
from .base import Model
from .codec import DocumentValue
from .events import ControlChange, Release, StoredEvent, Trigger
from .interface import (
    Address,
    Direction,
    EventType,
    InterfaceDocument,
    MixBinding,
    Parameter,
    Port,
    SequenceBinding,
    StreamBinding,
)
from .modulation import Unit
from .recording import AudioStream, RecordingDocument
from .samples.enums import SelectionMode
from .samples.instrument import InstrumentDocument
from .sequence import SequenceDocument
from .streams import AudioType


class DefinitionRecord(Model):
    document: DocumentValue
    references: dict[str, str] = Field(default_factory=dict)
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


class Instance(Model):
    definition: str
    parameters: dict[str, float]
    children: dict[str, str] = Field(default_factory=dict)


class EventDelivery(Model):
    instance: str
    port: str
    event: StoredEvent


class Composition:
    def __init__(
        self,
        root: str,
        definitions: dict[str, DefinitionRecord],
        parameters: dict[str, float] | None = None,
    ) -> None:
        self.definitions = definitions
        self.instances: dict[str, Instance] = {}
        self.root = root
        self._check_definitions(root, [], {})
        self._instantiate(root, 'root', parameters or {})
        self._validate_instances()

    def parameter_contract(self, identity: str, name: str) -> ParameterContract:
        document = self.definitions[identity].document
        if not isinstance(document, InterfaceDocument):
            raise ValueError(f'{identity}: no public interface')
        export = next((p for p in document.parameters if p.id == name), None)
        if export is None:
            raise ValueError(f'{identity}: unknown public parameter {name}')
        if isinstance(document, ArrangementDocument):
            node = next(n for n in document.body.nodes if n.id == export.binding.node)
            child = self.definitions[identity].references[node.definition.path]
            inherited = self.parameter_contract(child, export.binding.parameter)
            inherited = inherited.model_copy(
                update={
                    'default': node.parameters.get(
                        export.binding.parameter, inherited.default
                    )
                }
            )
        elif isinstance(document, InstrumentDocument):
            internal = next(
                (
                    p
                    for p in document.body.instrument.modulation.parameters
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
            raise ValueError(f'{identity}: unsupported configurable document')
        return _narrow(inherited, export)

    def port(self, instance: str, name: str) -> Port:
        document = self.definitions[self.instances[instance].definition].document
        if not isinstance(document, InterfaceDocument):
            raise ValueError(f'{instance}: document has no ports')
        port = next((p for p in document.ports if p.id == name), None)
        if port is None:
            raise ValueError(f'{instance}: unknown public port {name}')
        return port

    def rate(self, instance: str, timebase: str) -> Fraction:
        document = self.definitions[self.instances[instance].definition].document
        if not isinstance(document, InterfaceDocument):
            raise ValueError('document has no timebases')
        clock = next(t for t in document.timebases if t.id == timebase)
        return Fraction(clock.rate.numerator, clock.rate.denominator)

    def extent(self, instance: str, port_name: str) -> tuple[int, int | None]:
        port = self.port(instance, port_name)
        document = self.definitions[self.instances[instance].definition].document
        binding = port.binding
        if isinstance(binding, Address):
            child = self.instances[instance].children[binding.node]
            start, end = self.extent(child, binding.port)
            rate = self.rate(instance, port.stream.timebase) / self.rate(
                child, self.port(child, binding.port).stream.timebase
            )
            return exact_tick(start, rate), None if end is None else exact_tick(
                end, rate
            )
        if isinstance(document, SequenceDocument):
            return document.body.start, document.body.end
        if isinstance(document, RecordingDocument) and isinstance(
            binding, StreamBinding
        ):
            stream = next(s for s in document.body.streams if s.id == binding.stream)
            if isinstance(stream, AudioStream):
                return 0, stream.end
            starts = [f.start for f in stream.fragments if f.start is not None]
            ends = [f.end for f in stream.fragments if f.end is not None]
            return min(starts, default=0), max(ends, default=0)
        if isinstance(document, ArrangementDocument) and isinstance(
            binding, MixBinding
        ):
            extents = {
                t.id: max(
                    (
                        c.timeline_start + c.source_end - c.source_start
                        for c in document.body.clips
                        if c.track == t.id
                    ),
                    default=0,
                )
                for t in document.body.tracks
            }
            for bus in document.body.bus_order:
                extents[bus] = max(
                    (
                        extents[r.source]
                        for r in document.body.routes
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

    def events(self, instance: str, port_name: str) -> list[StoredEvent] | None:
        port = self.port(instance, port_name)
        document = self.definitions[self.instances[instance].definition].document
        if isinstance(document, SequenceDocument) and isinstance(
            port.binding, SequenceBinding
        ):
            return list(document.body.events)
        if isinstance(port.binding, Address) and port.direction == Direction.output:
            child = self.instances[instance].children[port.binding.node]
            events = self.events(child, port.binding.port)
            if events is None:
                return None
            ratio = self.rate(instance, port.stream.timebase) / self.rate(
                child, self.port(child, port.binding.port).stream.timebase
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
        document = self.definitions[self.root].document
        if not isinstance(document, InterfaceDocument):
            raise ValueError('root has no interface')
        requests: dict[tuple[str, str], tuple[int, int]] = {}
        for name in (
            outputs
            if outputs is not None
            else [p.id for p in document.ports if p.direction == Direction.output]
        ):
            self._request('root', name, start, end, requests)
        return requests

    def performance_trace(
        self, end: int, start: int = 0, outputs: list[str] | None = None
    ) -> list[EventDelivery]:
        """Replay instrument histories with pre-roll, without generating audio."""
        windows = self.evaluation_windows(start, end, outputs)
        deliveries: list[EventDelivery] = []
        for (path, port_name), (_, stop) in windows.items():
            document = self.definitions[self.instances[path].definition].document
            if not isinstance(document, InstrumentDocument):
                continue
            if any(
                s.mode in (SelectionMode.random, SelectionMode.shuffle)
                for s in document.body.instrument.selections
            ):
                raise ValueError(
                    f'{path}: deterministic selection execution is not defined'
                )
            output = self.port(path, port_name)
            for port in document.ports:
                if port.direction == Direction.input:
                    source, source_port = self._input_source(path, port.id)
                    events = self.events(source, source_port)
                    if events is None:
                        raise ValueError(
                            f'{source}: event payload requires a host provider'
                        )
                    self._deliver(
                        path,
                        port.id,
                        events,
                        self.rate(
                            source, self.port(source, source_port).stream.timebase
                        ),
                        Fraction(stop, 1) / self.rate(path, output.stream.timebase),
                        deliveries,
                    )
        return sorted(
            deliveries,
            key=lambda d: (
                Fraction(d.event.tick, 1)
                / self.rate(d.instance, self.port(d.instance, d.port).stream.timebase),
                d.event.ordinal,
                d.instance,
                d.port,
            ),
        )

    def _input_source(self, path: str, port_name: str) -> tuple[str, str]:
        if path == 'root':
            raise ValueError('offline evaluation requires supplied root input events')
        parent, node = path.rsplit('/', 1)
        instance = self.instances[parent]
        document = self.definitions[instance.definition].document
        assert isinstance(document, ArrangementDocument)
        address = Address(node=node, port=port_name)
        for edge in document.body.connections:
            if edge.destination == address:
                return instance.children[edge.source.node], edge.source.port
        for port in document.ports:
            if port.direction == Direction.input and port.binding == address:
                return self._input_source(parent, port.id)
        raise ValueError(f'{path}.{port_name}: required input is not supplied')

    def _request(
        self,
        path: str,
        name: str,
        start: int,
        end: int,
        requests: dict[tuple[str, str], tuple[int, int]],
    ) -> None:
        port = self.port(path, name)
        if port.direction != Direction.output:
            raise ValueError('evaluation must select output ports')
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
        document = self.definitions[self.instances[path].definition].document
        binding = port.binding
        if isinstance(binding, Address):
            child = self.instances[path].children[binding.node]
            ratio = self.rate(
                child, self.port(child, binding.port).stream.timebase
            ) / self.rate(path, port.stream.timebase)
            self._request(
                child,
                binding.port,
                exact_tick(start, ratio),
                exact_tick(end, ratio),
                requests,
            )
        elif isinstance(document, ArrangementDocument) and isinstance(
            binding, MixBinding
        ):
            relevant = {binding.track or binding.bus}
            for bus in reversed(document.body.bus_order):
                if bus in relevant:
                    relevant.update(
                        r.source for r in document.body.routes if r.destination == bus
                    )
            for clip in document.body.clips:
                if clip.track not in relevant:
                    continue
                lo = max(start, clip.timeline_start)
                hi = min(end, clip.timeline_start + clip.source_end - clip.source_start)
                if lo < hi:
                    self._request(
                        self.instances[path].children[clip.source.node],
                        clip.source.port,
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
        port = self.port(target, name)
        rate = self.rate(target, port.stream.timebase)
        converted = [
            e.model_copy(update={'tick': exact_tick(e.tick, rate / source_rate)})
            for e in events
        ]
        if isinstance(port.binding, Address):
            self._deliver(
                self.instances[target].children[port.binding.node],
                port.binding.port,
                converted,
                rate,
                end,
                result,
            )
            return
        document = self.definitions[self.instances[target].definition].document
        if not isinstance(document, InstrumentDocument):
            raise ValueError(f'{target}: no performance consumer')
        for event in converted:
            if event.tick < 0:
                raise ValueError('negative performance positions are unsupported')
            if not isinstance(event, (Trigger, Release, ControlChange)):
                raise ValueError('instrument accepts only performance events')
            document.body.validate_event(event)
            if (
                isinstance(event, Trigger)
                and event.pitch_hz is None
                and any(
                    s.mapping.pitch_tracking
                    and s.mapping.lowest_key <= event.key <= s.mapping.highest_key
                    and s.mapping.minimum_velocity
                    <= event.velocity
                    <= s.mapping.maximum_velocity
                    for s in document.body.slots
                )
            ):
                raise ValueError(f'{target}: pitch-tracked trigger requires pitch_hz')
            if Fraction(event.tick, 1) / rate < end:
                result.append(EventDelivery(instance=target, port=name, event=event))

    def _check_definitions(
        self, identity: str, stack: list[str], pins: dict[str, str]
    ) -> None:
        if identity in stack:
            raise ValueError(f'Definition cycle: {stack + [identity]}')
        if identity not in self.definitions:
            raise ValueError(f'Missing definition: {identity}')
        record = self.definitions[identity]
        document = record.document
        if not isinstance(document, ArrangementDocument):
            return
        for node in document.body.nodes:
            reference = node.definition
            child = record.references.get(reference.path)
            if child is None or child not in self.definitions:
                raise ValueError(
                    f'{identity}/{node.id}: missing definition {reference.path}'
                )
            if reference.sha256 is not None:
                if child in pins and pins[child] != reference.sha256:
                    raise ValueError(f'Contradictory definition pins: {child}')
                pins[child] = reference.sha256
                if self.definitions[child].sha256 != reference.sha256:
                    raise ValueError(f'Definition digest mismatch: {child}')
            self._check_definitions(child, stack + [identity], pins)

    def _instantiate(self, identity: str, path: str, values: dict[str, float]) -> None:
        document = self.definitions[identity].document
        if not isinstance(document, InterfaceDocument):
            raise ValueError(f'{path}: definition cannot be instantiated')
        contracts = {
            p.id: self.parameter_contract(identity, p.id) for p in document.parameters
        }
        if unknown := values.keys() - contracts.keys():
            raise ValueError(f'{path}: unknown public parameters {sorted(unknown)}')
        configured = {k: values.get(k, v.default) for k, v in contracts.items()}
        for name, value in configured.items():
            if not contracts[name].minimum <= value <= contracts[name].maximum:
                raise ValueError(f'{path}/{name}: parameter outside public range')
        children = {}
        if isinstance(document, ArrangementDocument):
            for node in document.body.nodes:
                child_values = dict(node.parameters)
                for export in document.parameters:
                    if export.binding.node == node.id:
                        child_values[export.binding.parameter] = configured[export.id]
                child = self.definitions[identity].references[node.definition.path]
                child_path = f'{path}/{node.id}'
                children[node.id] = child_path
                self._instantiate(child, child_path, child_values)
        self.instances[path] = Instance(
            definition=identity, parameters=configured, children=children
        )

    def _compatible(
        self,
        source: str,
        output: str,
        target: str,
        input_name: str,
        forwarded: bool = False,
    ) -> None:
        left, right = self.port(source, output), self.port(target, input_name)
        if not forwarded and (
            left.direction != Direction.output or right.direction != Direction.input
        ):
            raise ValueError('connection must join an output to an input')
        a, b = left.stream, right.stream
        ratio = self.rate(target, b.timebase) / self.rate(source, a.timebase)
        if isinstance(a, AudioType) and isinstance(b, AudioType):
            valid = ratio == 1 and a.channels == b.channels
        elif isinstance(a, EventType) and isinstance(b, EventType):
            valid = set(a.kinds) <= set(b.kinds)
            events = self.events(source, output)
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
        for path, instance in self.instances.items():
            document = self.definitions[instance.definition].document
            if not isinstance(document, ArrangementDocument):
                continue
            supplied = {c.destination for c in document.body.connections}
            for port in document.ports:
                if isinstance(port.binding, Address):
                    child = instance.children[port.binding.node]
                    if self.port(child, port.binding.port).direction != port.direction:
                        raise ValueError(
                            'forwarded port direction disagrees with target'
                        )
                    if port.direction == Direction.input:
                        supplied.add(port.binding)
                        self._compatible(path, port.id, child, port.binding.port, True)
                    else:
                        self._compatible(child, port.binding.port, path, port.id, True)
            for edge in document.body.connections:
                self._compatible(
                    instance.children[edge.source.node],
                    edge.source.port,
                    instance.children[edge.destination.node],
                    edge.destination.port,
                )
            for node, child in instance.children.items():
                child_doc = self.definitions[self.instances[child].definition].document
                if isinstance(child_doc, InterfaceDocument):
                    for port in child_doc.ports:
                        if (
                            port.direction == Direction.input
                            and Address(node=node, port=port.id) not in supplied
                        ):
                            raise ValueError(
                                f'{child}.{port.id}: required input is not supplied'
                            )
            for edge in document.body.connections:
                source = instance.children[edge.source.node]
                if not isinstance(
                    self.port(source, edge.source.port).stream, EventType
                ):
                    continue
                events = self.events(source, edge.source.port)
                if events is not None:
                    self._deliver(
                        instance.children[edge.destination.node],
                        edge.destination.port,
                        events,
                        self.rate(
                            source, self.port(source, edge.source.port).stream.timebase
                        ),
                        Fraction(0),
                        [],
                    )
            tracks = {t.id: t.stream for t in document.body.tracks}
            for clip in document.body.clips:
                child = instance.children[clip.source.node]
                port = self.port(child, clip.source.port)
                stream = tracks[clip.track]
                if (
                    port.direction != Direction.output
                    or not isinstance(port.stream, AudioType)
                    or port.stream.channels != stream.channels
                    or self.rate(child, port.stream.timebase)
                    != self.rate(path, stream.timebase)
                ):
                    raise ValueError(f'{path}/{clip.id}: incompatible clip source')
                start, end = self.extent(child, port.id)
                if (
                    clip.source_start < start
                    or end is not None
                    and clip.source_end > end
                ):
                    raise ValueError(f'{path}/{clip.id}: clip exceeds source extent')


def exact_tick(tick: int, ratio: Fraction) -> int:
    value = tick * ratio
    if value.denominator != 1:
        raise ValueError(f'event position {value} is not an exact integer tick')
    return value.numerator


def _narrow(inherited: ParameterContract, export: Parameter) -> ParameterContract:
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
