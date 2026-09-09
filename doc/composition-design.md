# Document composition design

Status: implemented for the initial offline profile in document version 2.
Names remain subject to the separate naming review. Ufor resolves interfaces and
event histories; Recs renders nested recording arrangements. Sampler execution
remains deferred.

A document can use a recording, another mix or an instrument through its public
interface. Four questions describe the composition.

## 1. What definition does this instance use?

A node identifies an instance and directly references its definition:

```toml
[[body.nodes]]
id = "piano"
definition = { path = "instruments/piano.toml" }
parameters = { level_db = -6.0 }
```

A document reference contains a relative `path` and, when pinned, a `sha256` of
its bytes. Static references such as tunings use the same reference structure
without creating a running node. The dependency graph is derived from these
references; there is no separate dependency table or source-alias collection.

Two nodes may reference the same file. They share a definition and immutable
media, but each has independent state. A nested instance is identified by its
full node path, such as `concert/drums/room-mic`. Node IDs are local to their
container and independent of display names or document IDs.

## 2. What does it expose?

A document exposes named input ports, output ports and configuration parameters.
Its private buses, streams and processing details cannot be addressed externally.

Each public declaration contains its binding in the same record. For example,
an arrangement can export its internal track directly:

```toml
[[ports]]
id = "main"
direction = "output"
stream = { timebase = "audio", channels = ["left", "right"] }
binding = { track = "mix", start = 0, end = 480000, gain = 1.0 }
```

This fragment uses the existing `AudioType` defaults for family, quantity and
unit. The containing document declares the referenced track and timebase.
Bindings select a recording stream, a sequence body, an instrument input/output,
a track/bus, or a child's public port as appropriate to the document kind.
There is no second output declaration in the body. Forwarded inputs likewise
carry their internal destination in the public declaration. A file destination
names the public output; referencing a child never runs that child's destinations.

A public parameter binds to one internal `{ node, parameter }` address. Its unit,
range and default are inherited from that target. An export may narrow the range
or change the default, but cannot change the unit or widen the permitted range.
The effective default must remain within the effective range. A resolved
interface exposes the resulting contract without requiring copies in the file.
Multiple exports cannot address the same internal parameter.

Construct an instance from its definition plus its supplied public parameter
values. At each nesting boundary, the bound target's configured value is the
inherited default, an explicit export default replaces it, and a supplied value
replaces that default. Unknown parameters and out-of-range values are errors.
The referenced file is never modified. The definition determines what those
settings mean for voices, lights or other internal objects; composition adds no
separate instrument/voice scope system. Internal modulation keeps its own rules.

## 3. What connects to what?

A port address is `{ node, port }`. Connections join output ports to input ports;
clips read windows from output ports and place them on tracks. These operations
share addresses but have different timing behavior.

```toml
[[body.connections]]
source = { node = "notes", port = "performance" }
destination = { node = "piano", port = "performance" }
```

Connections must match the producer's and consumer's resolved contracts. Audio
contracts include quantity, unit, ordered channel layout and sample rate.
Event contracts include accepted/emitted kinds and a clock. Output event kinds
must be a subset of the receiving input's kinds. An empty sequence still declares
its contract. Clock IDs are local names, so compatibility compares their meanings.

Clock conversion preserves the physical time of an event. For example, tick 5
at 1,000 ticks/second is tick 240 at 48,000 ticks/second. This is distinct from
resampling audio, converting MIDI into performance events or remapping channels.
Such changes require explicitly defined operations, not guesses by the host.

Fan-out observes one producer instance. It does not run that producer separately
for each connection. Combining sources requires defined mixing or merging rules;
audio tracks and buses retain their existing summing and gain semantics. Required
inputs must be connected or exposed for the caller to supply.

The [full example](composition-example.md) mixes a rehearsal recording, a nested
drums arrangement and a piano driven by a sequence. It uses four nodes, one event
connection, three audio clips and one public output. No intermediate rendered
files are required by the composition itself.

## 4. What happens over time?

Given the same inputs and initial configuration, an instance has one output
history. Two clips reading that instance reuse its history; two instances own
independent histories. Reading a later passage must preserve earlier state
changes, by replaying from the initialization point or using an equivalent
checkpoint. Evaluation order, block size and caching must not change the result.

A clip reads a half-open source interval and places it at a destination position.
At equal rates and speed one, source tick `source_start + k` appears at parent tick
`timeline_start + k`. Moving the clip does not move the producer's incoming
connections. To move a whole performance, place the output of the arrangement
containing its sequence and instrument together.

An offline evaluation request names outputs and **one finite half-open interval**.
That interval already includes any desired tail. Ending a sequence generates no
Release or other events. Continue existing voices and processing through the
requested end; clip and exported-output boundaries still apply. Increasing the
request alone cannot recover audio excluded by those boundaries. An authoring
command may calculate longer intervals for a desired tail, but the core format
has no second tail-duration or truncation mode.

Propagate requested windows through the graph. Cropping a later child passage
may require child positions beyond the parent's end. Audio outside scheduled
clips contributes silence; asking a clip to read beyond a finite recording's
bounds is an error. Gaps retain their recording semantics. Generative outputs
are evaluated for the requested window rather than assigned a guessed duration.

Preserve event ordering and trigger identity. Separate receiving instances have
separate part/trigger namespaces, even when fed identical events. Flattening a
nested graph is permitted only if these state and timing rules are preserved.

The [implementation plan](composition-implementation.md) defines the first
supported profile, resolution and packaging, migration, and acceptance criteria.
Those implementation limits do not restrict the general composition concepts.

## Additional work beyond the prompt

None.
