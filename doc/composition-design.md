# Document composition design

Status: proposed design, not an implemented document profile. Field spellings
below are provisional pending the naming review. The examples illustrate the
proposal; the current codec does not accept the new fields.

A mix should be able to consume the output of a recording, another mix, or an
instrument without knowing how that output is produced. This design defines
that boundary. It does not implement a sampler, processor engine or renderer.

## Decisions

1. A document declares its public inputs, outputs and parameters. Its internal
   streams, buses, slots and processing nodes remain private.
2. A dependency identifies a reusable definition. A node instantiates that
   definition. Connections and clips address a node's public ports.
3. Each node has independent state. Reusing the same definition does not share
   voices, controls, selection counters or transport state.
4. Referencing a document does not require rendering it to an intermediate file.
   A host may render or cache internally only when it preserves the semantics.
5. Composition initially supports sampled audio and native performance events,
   physical time, finite evaluation requests and acyclic connections.
6. Tunings, scales and other static definitions are dependencies, not streams.
   A raw MIDI connection does not implicitly become performance events or audio.

These decisions refine the existing Recs master plan's document, dependency,
node and port model. They do not rename its concepts or introduce a second
meaning for Recs' existing editing recipes.

## Definitions, instances and addresses

A dependency has a local `id`, a relative document `path`, and an optional
`sha256` of the exact referenced document bytes. The digest is required when
sealing a portable composition. A filename locates a document; the document's
own `id` is descriptive identity, not a global lookup key.

A node has a local `id`, a `dependency` reference and initial parameter values.
Two nodes may refer to one dependency. They share the definition and immutable
media, but each receives its own execution state. Node identity is the complete
nested instance path, such as `concert/drums/room-mic`, rather than the child
node's unqualified name.

A port address is `{ node, port }`. A parameter address retains the existing
`{ node, parameter }` structure. They are different address types. A string such
as `"piano.audio"` is not another supported address syntax.

A connection joins an output port to an input port. A clip selects a finite
interval from an audio output and places it on an arrangement track. Both use
the same port address. Neither accepts a private child bus, file path or Python
object as a substitute for a public output.

Do not keep an additional `sources` alias collection between nodes and clips.
The new clip's `source` is directly `{ node, port }`, replacing today's source ID.
Document dependency IDs, node IDs and public port IDs each have their own
namespace. Public port IDs are unique across both directions within a document.
Display-name changes do not alter references.

## Public interfaces

Each port declares an `id`, a direction and a stream contract. A document body
binds the public port to exactly one internal producer or consumer. Public
contracts appear once at the root; bindings do not repeat their types.

| Document | Public interface | Body binding |
| --- | --- | --- |
| Recording | Selected audio or native event outputs | Stable recording stream ID |
| Sequence | A native event output | Sequence body |
| Sample instrument | Performance input and audio output | Existing performance input and sample mixer |
| Arrangement | Exported outputs and any forwarded inputs | Internal track/bus or child port |

An arrangement can therefore expose an instrument's performance input, connect
that input to the child, mix its audio with other children, and export the
result. External users need not know which internal child receives the notes.
Exports and forwarded inputs are explicit body bindings, not connections with
special node names such as `self` or `parent`.

Root `ports` replaces instrument `performance_port`, `audio_port` and `output`.
Arrangement output IDs become public port IDs; their existing source/range/gain
settings remain body bindings. A file destination continues to name a public
output port and stays outside the reusable signal definition. Child destinations
are never executed just because another document references that child.

### Stream compatibility

The audio contract reuses `AudioType`: sampled full-scale audio amplitude, ordered
channel names and a physical timebase. Connections require matching channel
layouts and sample rates. Equal channel counts alone are insufficient. Clock IDs
are local names: resolve them before comparison. Two clocks called `audio` may
have different rates; clocks with different names may have the same rate.

The native event contract declares a timebase and a nonempty set of accepted or
emitted event kinds, serialized as a unique list. A sequence declaring only
`trigger` and `release` can connect to an input accepting those plus
`control_change`. An output's declared kinds must be a subset of the input's.
For finite sequences, validation verifies every stored event against the declared
output kinds. An empty sequence still has a declared contract.

The first instrument performance input accepts `trigger`, `release` and
`control_change`. Event streams share the receiving graph's physical tick rate
in the first profile. The consumer validates control domains and requires
`pitch_hz` for any triggered sample that needs pitch tracking. There is no
implicit MIDI-note-to-frequency conversion or hidden selection of a tuning.

No implicit resampling, channel remapping, unit conversion or event conversion
occurs. Incompatible edges produce diagnostics with both resolved contracts.
A later explicit adapter can perform a conversion. Merely adding its name to a
document does not make an unsupported adapter executable.

## Inputs, mixing and parameters

An input has at most one incoming connection in the initial profile. Audio
mixing continues to use arrangement tracks and buses with the current explicit
gain rules. Arbitrary event merging is deferred: overlapping trigger IDs and
same-tick ordering require a deliberate merge contract. Outputs may fan out;
all consumers observe the same producer instance rather than causing it to run
once per edge. Required inputs must be connected or forwarded to a public input.
Missing inputs are errors, not silent sources of zeroes or empty event streams.

Public numeric parameters reuse the existing unit, domain, default and scope
semantics of `modulation.Parameter`. A public parameter has a local ID; the body
binds it to one existing internal parameter address. That binding replaces the
internal address in the public declaration, rather than duplicating the same
default and range in two places. Preparation resolves the binding and checks
that the public domain is a subset of the internal domain and units agree.

A node's parameter values are overrides of public defaults only. Missing values
use those defaults. Unknown parameters, private addresses and values outside the
public domain are rejected. Overrides are applied before state initialization
and do not modify the dependency file. Exporting one parent parameter through
several layers follows these same rules at every boundary; its supplied value
replaces the child node's initial value at that binding. Multiple parent exports
targeting the same internal parameter are invalid.

Initially, public overrides are initialization-time constants with instrument
scope, not per-voice overrides. Existing internal modulation continues unchanged.
When an exported setting supplies a per-voice default, the instance-level
constant initializes that default for every voice; it does not change the scope
of internal modulation or merge the voices' state.
Dynamic automation across document boundaries, parameter macros and conflicting
external writers require a later control-connection design. A public parameter
cannot secretly modify several private parameters at once.

## Worked example: rehearsal, drums and piano

Suppose these four dependencies declare the following interfaces:

| Dependency | Port | Contract |
| --- | --- | --- |
| `rehearsal` | `desk` output | Stereo audio, 48,000 frames/second, at least ten seconds |
| `drums` | `main` output | Nested arrangement, same stereo layout/rate, at least ten seconds |
| `notes` | `performance` output | Native trigger/release/control events, 48,000 ticks/second |
| `piano` | `performance` input; `audio` output | Accepts those events; emits matching stereo audio |

`piano` also explicitly exports `level_db`, an instrument-scoped parameter bound
to its existing per-voice processing volume. This export is part of the proposed
piano interface, not a parameter inferred from the name.

The parent needs only these declarations. The drums arrangement can itself use
recordings and instruments behind its `main` output.

This proposed parent document contains the complete wiring and ten-second audio
placement. The dependency files and their proposed interfaces are prerequisites;
this is not an executable fixture shipped with the implementation.

```toml
format = "recs"
version = 1
kind = "arrangement"
id = "concert"
name = "Rehearsal with drums and piano"
timebases = [{ id = "audio", rate = { numerator = 48000 } }]

[[dependencies]]
id = "rehearsal"
path = "recordings/rehearsal.toml"

[[dependencies]]
id = "drums"
path = "mixes/drums.toml"

[[dependencies]]
id = "notes"
path = "sequences/piano.toml"

[[dependencies]]
id = "piano"
path = "instruments/piano.toml"

[[ports]]
id = "main"
direction = "output"
stream = { family = "sampled", quantity = "audio_amplitude", unit = "full_scale", timebase = "audio", channels = ["left", "right"] }

[body]
timebase = "audio"

[[body.nodes]]
id = "rehearsal"
dependency = "rehearsal"

[[body.nodes]]
id = "drums"
dependency = "drums"

[[body.nodes]]
id = "notes"
dependency = "notes"

[[body.nodes]]
id = "piano"
dependency = "piano"
parameters = { level_db = -6.0 }

[[body.connections]]
source = { node = "notes", port = "performance" }
destination = { node = "piano", port = "performance" }

[[body.tracks]]
id = "mix"
stream = { timebase = "audio", channels = ["left", "right"] }

[[body.clips]]
id = "rehearsal"
source = { node = "rehearsal", port = "desk" }
track = "mix"
source_start = 0
source_end = 480000
timeline_start = 0

[[body.clips]]
id = "drums"
source = { node = "drums", port = "main" }
track = "mix"
source_start = 0
source_end = 480000
timeline_start = 0

[[body.clips]]
id = "piano"
source = { node = "piano", port = "audio" }
track = "mix"
source_start = 0
source_end = 480000
timeline_start = 0

[[body.outputs]]
id = "main"
source = "mix"
start = 0
end = 480000

[[destinations]]
port = "main"
path = "renders/concert.wav"
format = "wav"
```

The overlapping clips sum according to the existing audio-track behavior. The
piano notes contain explicit target frequencies where required. The host
initializes piano controls and selection counters, applies notes in order and
supplies its audio to the mix. Until an appropriate instrument engine exists,
Ufor can validate this composition but a host must report the piano realization
as unsupported. It must not quietly omit that contribution.

## Time, state and finite evaluation

All instances start at local tick zero with defaults plus overrides. Direct
connections align those origins and advance at speed one. The initial profile
rejects negative evaluation positions and differing connected physical rates.
No parent tempo implicitly warps a recording or changes a child's timing.

An instance defines one reproducible output history for its inputs and initial
parameters. Clips read windows of that history. A clip maps source tick
`source_start + k` to parent tick `timeline_start + k` for integer `k` in its
half-open range. This placement does not retime the producer's incoming
connections. To move a complete performance, place the audio output of the
arrangement that contains its sequence and instrument together.

Two clips reading the same node reuse that history; they do not retrigger it.
Two nodes referencing the same instrument or arrangement have independent
histories. This distinction applies recursively and prevents evaluation block
size or the order of output requests from changing the result.

Reading a stateful child's window starting after zero requires replay from zero,
or an equivalent verified checkpoint. Skipping earlier notes, control changes
or selection decisions is incorrect. A compiler may flatten nested arrangements
only when it preserves instance namespaces, state and these time mappings.
Preparation must reject unresolved randomness and external live inputs in this
reproducible offline profile. Existing random/shuffle selection declarations
need the separately planned algorithm, seed and action traces before execution.

Preparation propagates requested source windows through clips and connections.
A parent rendering ten seconds may need later child ticks when a clip reads a
later passage. Source extent checks therefore use the propagated child request,
not just the parent's duration. Recording gaps retain their declared semantics;
requests beyond known finite source bounds are errors. An instrument has no
intrinsic finite audio length, so its extent comes from the evaluation request.

Every offline request selects public outputs and a finite half-open interval,
with either truncation or an explicitly bounded additional tail duration. The
example requests `[0, 480000)` with truncation. The end of the note sequence
means no more events; it does not fabricate Release events or silence existing
voices. Evaluate voices and nested processors through the requested end, then
stop. Extending the tail extends the required upstream evaluation too. A host
may not guess a finite duration for an open live input.

Preserve event ordering by `(tick, ordinal)`. Trigger identities are scoped by
the receiving instance as well as their existing part/trigger IDs, so separate
pianos cannot release each other's voices. Fan-out to separate consumers gives
each consumer its own lifecycle, with the same incoming event sequence.

## Resolution, portability and validation

Paths resolve relative to the document containing the dependency declaration,
never the process working directory. Dependency paths use relative POSIX syntax;
`..` may select a sibling within a declared package root. Portable-package
resolution rejects absolute paths, URLs and paths escaping that root, including
symlink escapes. This does not change existing asset-path rules. Ufor performs
no filesystem reads, downloads or automatic dependency search.

The host loads documents and supplies Ufor with their resolved definitions and
identities. Aliases to the same resolved file share its definition; node state
remains separate. A sealed package pins every dependency edge and existing media
assets by SHA-256. Its root document digest identifies that exact snapshot.
Document edits deliberately invalidate those pins until the package is resealed.
Relocation preserves contents and relative relationships, or regenerates digests
if an exporter rewrites paths. The host verifies bytes before using a pin.

Validation has three stages:

1. **Local format validation:** legal fields, unique identities, well-formed
   addresses, existing local node/dependency references and valid body bindings.
2. **Resolved composition validation:** referenced public interfaces, parameter
   bindings and overrides, compatible streams, connected required inputs,
   dependency cycles and signal cycles, and known source extents.
3. **Host preparation:** assets and hashes, supported implementations, necessary
   finite evaluation windows, state initialization and execution capabilities.

Ufor owns the first two stages as pure operations on supplied documents. Hosts
own I/O and execution in the third. Diagnostics identify the nested instance
path and offending edge, for example `concert/piano.performance: output kind
midi is not accepted`. Missing definitions, private ports, ambiguous inputs and
unsupported operations fail explicitly.

Both the document dependency graph and the connected execution graph must be
acyclic in the first profile. Check execution cycles across exported boundaries,
including paths through a child. Treat each child conservatively as depending
on all its connected inputs; finer per-output dependency analysis is deferred.
An internal delayed-feedback DSP algorithm does not authorize document recursion.

## Changes from the implemented models

| Current structure | Proposed change |
| --- | --- |
| Common `Document` header | Add optional dependencies and a public interface to relevant document kinds; retain current header spelling |
| `arrangement.SourceSpec` | Replace record/file/memory alternatives with dependency-backed nodes; clips select node ports directly |
| `RecordSelector` in a parent | Resolve the selection when authoring a recording's exported port; parent references that port |
| Raw audio file source | Author a recording document around its media and channel description |
| Application memory source | Keep as a host realization of a declared source; no process-local memory key in portable documents |
| `ClipSpec.source` | Structured node/output address; preserve integer-frame placement and gains |
| Arrangement `RouteSpec` | Retain track/bus mixing semantics; new typed connections handle child inputs |
| Arrangement outputs | Bind public output ports to existing internal sources and ranges |
| Sample instrument port fields | Replace with the shared interface and explicit instrument-body bindings |
| Sequence and recording streams | Explicit public exports with native event/audio contracts |
| Modulation parameter addresses | Reuse for body bindings; export only declared initialization parameters initially |
| File destinations | Continue to target exported outputs; never imply evaluation of child destinations |

No compatibility adapter or parallel old source representation is planned.
Migration changes definitions and references; it does not rewrite recorded media.
Recs' command recipes continue producing final arrangements. Their existing
`CompositionEdit` name does not turn those recipes into executable signal graphs.

## Implementation sequence and acceptance criteria

1. Add shared interfaces, dependency/instance references and stream contracts.
   Add proposed-profile schemas and portable positive/negative examples. Decide
   the release's document-version policy explicitly before changing accepted wire
   data; the version-1 examples above do not establish that policy.
2. Implement pure recursive resolution validation over host-supplied documents.
   Cover missing/private ports, distinct clock IDs with equal rates, equal IDs
   with different rates, dependency aliases/cycles, input fan-in rejection and
   parameter binding errors.
3. Migrate recording, sequence, instrument and arrangement interfaces together.
   Replace parent selectors and sources everywhere, update Recs authoring and
   loading, and retire the old model fields rather than maintaining two paths.
4. Establish portable instance and timing traces without generating audio: two
   instances of one definition, event fan-out, nested cropping with pre-roll,
   repeat reads, explicit tails and control/trigger isolation. Add an event-only
   test double for the worked piano graph; do not call it a sampler.
5. Add host execution for recording-plus-nested-arrangement audio using Recs'
   existing renderer. Compare flat and nested results and block-size independence.
   Sequence-driven instruments remain a preparation milestone until their voice
   model and engine are ready.

Completion of the format work means the worked example can be loaded, resolved
and checked independently of any audio implementation. Completion of host nested
mixing means equivalent flat and nested recordings produce equivalent output.
These are separate acceptance gates.

## Deferred decisions

The naming review remains separate. General processor graphs, implementation and
plugin bindings, musical tempo maps, event merging, time stretching, live radio
sections, lighting/spatial contracts and dynamic public-parameter automation
remain later work. This design creates no placeholder fields for those features.

## Additional work beyond the prompt

None.
