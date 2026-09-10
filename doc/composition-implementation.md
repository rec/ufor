# Score composition implementation plan

Status: implemented for score version 3. The [simplified design](composition-design.md)
and [worked example](composition-example.md) are accepted by the codec. Ufor owns
pure resolution and performance-delivery traces; Recs owns nested audio rendering.
Traces establish delivery and instance isolation, not sample selection or voice
execution. The terminology below is the implemented naming scheme.

## First supported profile

Keep initial implementation limits here rather than building them into the
meaning of composition:

- Sampled audio and native performance events, with physical clocks. Audio
  connections require matching rates and ordered channel layouts.
- Event connections may use different physical tick rates if every converted
  timestamp is exactly representable as a destination integer tick. Use rational
  arithmetic; reject unrepresentable positions until an explicit quantization
  policy is supported. Preserve `(tick, ordinal)` order after conversion.
- Speed-one placement, origins aligned at zero, and nonnegative evaluation
  positions. Stateful instances initialize at zero. Musical tempo maps,
  time stretching and other origin mappings remain later implementations.
- Reproducible offline evaluation over finite requested intervals. Reject
  unresolved randomness and external live inputs for this profile. Existing
  random/shuffle selection needs the separately planned algorithm, seed and
  action traces before execution.
- Each input receives at most one connection or one public forwarding binding.
  Outputs can fan out. Required inputs must be supplied; implicit silence or
  empty-event defaults are not supplied. Arbitrary event merging is deferred
  until trigger-identity and same-tick ordering rules are defined.
- Public parameters are numeric configuration values supplied at initialization.
  Dynamic external automation and macros are deferred. Reuse internal parameter
  domain/default validation without duplicating its voice/instrument scopes in
  the composition interface.
- Both the definition-reference graph and signal graph are acyclic. Check signal
  cycles across public boundaries. Initially treat a child's outputs as depending
  on all its connected inputs; this conservative implementation may reject some
  valid graphs until per-output dependency analysis is available. Internal DSP
  feedback does not permit recursive score references.

A sample instrument performance input accepts `trigger`, `release` and
`control_change`. Validate supplied controls and require `pitch_hz` for triggered
samples needing pitch tracking. Raw MIDI does not implicitly select a tuning or
become native performance events. Unsupported realization is a preparation error,
not permission to omit a contribution. Waveform and sampler execution remain
separate work.

## Public declaration bindings

Keep each declaration, its contract and its binding in one root record. Define
one typed binding variant for each actual internal target; do not introduce
parallel root declarations and body exports.

| Score | Public port binding |
| --- | --- |
| Recording | Stable audio/native-event stream ID |
| Sequence | Its sequence body |
| Sample instrument | Its performance input or audio mixer output |
| Arrangement | Track/bus, or child `{ part, port }` |

A track/bus output binding retains existing gain and optional frame-range
settings. Inputs bind to consumers, outputs to producers. Input and output names are each unique within their collection. Each declaration binds exactly once and is checked
against its internal target's contract. Child bindings can address public inputs and outputs
only. Native sequence declarations must match their stored event kinds.

Parameter declarations store an ID, one internal parameter address, and only any
deliberate default/range overrides. Resolve inherited unit, range and configured
default recursively. Reject widened ranges, invalid defaults, duplicate target
bindings and unknown supplied values. A parent value reaches its bound child
before that child's state is initialized. Effective interface descriptions can be
computed for editors and hosts; they are not another serialized copy.

## Resolution and portability

A score reference is `{ path, sha256? }` wherever a definition is needed.
Parts carry it directly; static definition fields use the same structure without
instantiation. Walk these references to derive dependencies, rather than maintaining
a dependency table. Repeated references can share loaded definitions, never part
state. Contradictory pins for the same resolved file are errors.

Paths resolve relative to the containing score, not the process working
directory. Use relative POSIX paths. A portable package declares a root;
`..` may reach siblings inside that root, but absolute paths, URLs and escapes
through either paths or symlinks are rejected. Existing asset-path rules remain
unchanged. Ufor performs no I/O, downloads or automatic file searches.

The host supplies resolved scores and identities to pure Ufor validation.
Aliases to the same file must be recognized for cycle detection and definition
sharing. Part identities still use their complete nested instance paths.

A sealed package pins every score reference and media asset by SHA-256. The
root score digest identifies the snapshot. Verify hashes against actual bytes.
Edits invalidate pins; resealing updates affected references recursively. Moving
a package preserves contents and relative relationships, or requires new digests
if an exporter rewrites paths. There is no separate composition dependency lock
structure. Sealing/export tooling is not provided by this implementation; the
resolver checks pins supplied by callers. The conformance package contains
synthetic asset metadata and is not a sealed, renderable media package.

## Validation ownership

1. **Local format:** fields, unique IDs, local part references, structured
   addresses, binding variants and locally checkable contracts.
2. **Resolved composition:** referenced public inputs and outputs and parameters, inherited
   contracts and configuration, required inputs, cycles, stream compatibility,
   exact event-clock conversion and known source extents.
3. **Host preparation:** load and verify bytes, select supported implementations,
   propagate finite requests, check remaining media-dependent bounds and
   initialize state.

Ufor owns the first two stages on supplied definitions. Hosts own I/O and
execution. If a property requires external payload data, validate its declaration
in Ufor and verify the payload during preparation. Unknown event positions cannot
be declared exactly convertible merely because the header's clocks are valid.
Report the nested instance path and both incompatible contracts in diagnostics.

A request's end already includes any desired tail. Propagation follows the actual
clip and export windows, not a blanket extension of every source. For example,
a twelve-second piano clip can coexist with ten-second recording clips without
requesting nonexistent recorded frames. Never fabricate release events at the
end of a sequence.

## Migration from version 1

| Current structure | Replacement |
| --- | --- |
| `arrangement.SourceSpec` record/file/memory alternatives | Parts with direct score references |
| `ClipSpec.source` ID | `{ part, port }`, retaining frame placement and gains |
| Parent `RecordSelector` | Select recording streams when authoring exported ports; parent uses the public input or output |
| Raw audio-file source | A recording definition describing its media and channels |
| Process-local memory source | Host realization of a declared source, not a portable memory key |
| Separate arrangement outputs and public contracts | One public declaration containing the internal binding, range and gain |
| Instrument version-2 `ports` | Shared public input or output declarations with bindings |
| Sequence and recording streams | Explicit audio/native-event public exports |
| Public parameter descriptions | A binding plus optional range/default overrides; inherit the remaining contract |
| File destinations | Continue selecting public outputs; child destinations are not run implicitly |

Retain track/bus routes for existing audio mixing and use typed connections for
child inputs. Replace old source and export representations everywhere rather
than maintain compatibility adapters. No media rewrite is needed. Recs editing
recipes still produce arrangements; `CompositionEdit` is not an execution graph.

## Stages and acceptance criteria

1. Implement score-reference values, instance records, public declarations
   with bindings, and audio/native-event contracts. Establish the score-version
   policy before changing accepted wire data. The implementation uses version 3,
   rejects earlier versions and includes a schema and portable composition fixture.
2. Add pure recursive validation over host-supplied definitions. Cover missing
   and private ports, invalid bindings/defaults, duplicate IDs, aliases and cycles,
   incompatible layouts, input fan-in, and exact/inexact event-clock conversions.
3. Migrate recording, sequence, instrument and arrangement interfaces together.
   Update Recs authoring, resolution and loading; retire old fields. Ensure no
   hidden dependency table or duplicate body export remains.
4. Establish event/state traces without audio generation: two instances of one
   definition, fan-out, nested cropping with replay, repeated reads, parameter
   inheritance, and trigger isolation. Test a longer request with a short
   recording clip and a longer generative clip. Cover export/clip truncation and
   absence of synthetic Release events. Use an event-only test double for the
   example piano graph, not a sampler implementation.
5. Implement host nested recording arrangements using Recs' existing renderer.
   Compare flat/nested output and block-size independence. Sequence-driven
   instruments wait for the separate voice model, preparation and engine work.

The format milestone is loading, resolving and checking the worked example
without an audio engine. The host milestone is equivalent output for equivalent
flat and nested recording arrangements. These are separate acceptance gates.

The implementation entry points are `ufor.interface`, `ufor.composition.Composition`
and `recs.edit.nested`. Tests cover the worked example, independent instances,
fan-out, inherited parameters, exact clock conversion, crop pre-roll, tails and
flat/nested audio equivalence under separate window requests. The Recs renderer
currently materializes child outputs in memory; it is not a streaming engine.

Recs authoring wraps selected files or recording streams in recording definitions.
Dry runs supply these definitions in memory and write nothing. Existing editing
recipes reconstruct prepared stage definitions and audio through a host provider;
the recipe remains the replayable artifact. An individual extracted stage is not
a standalone media package. Saved native arrangement paths are rebased relative
to their containing score. Imported media definitions may be sealed without
capture timestamps or journals; captured sessions retain those diagnostics.

Light animation scores now use the same resolver, named parts and parameter
exports. Their component contracts, layouts, exact cue clocks and mathematical
operations are specified in [light-format.md](light-format.md). Lyte integration
is intentionally deferred to [port-lyte.md](port-lyte.md).

Later capabilities include musical time, live radio sections,
processor and plugin bindings, dynamic public automation and event
merging. Do not add placeholder fields for them during this implementation.

## Additional work beyond the prompt

None.

## Version 3 names and migration

`Score` replaces `Document`. A score has a machine `name` and a display `title`;
all formerly `id`-named fields in Ufor now use `name`. Existing descriptive names
on sample slots become titles too. Capture identifiers such as `source_id` and
`trigger_id` retain their distinct operational meanings.

An arrangement contains `parts`. A `Part` has a `name`, a `score` (`ScoreVersion`,
with a relative path and optional SHA-256), and parameter settings. Public
configuration declarations use `ParameterExport`; internal modulation declarations
remain `Parameter`.

Replace `ports` with separate `inputs` and `outputs`, removing `direction`.
`InputSelection` is `{ name, input }`; `OutputSelection` is `{ name, output }`.
These names select a part and one of its declared inputs or outputs. Inputs and
outputs may use the same name because their selections are distinct. File
render destinations select an `output`. Parameter targets use `{ name, parameter }`.

The codec entry points are `parse_score`, `score_toml`, and `score_schema`.
Version 2 is rejected; migrate metadata explicitly and retain the previous file
when it is production material. Media payloads are unchanged. Recs' two production
recordings retain their version-2 metadata under `migration/recording-v2.toml`.
Network ports and ordinary filesystem names are unaffected. Recs SFZ metadata
comments use version 2 for the renamed name/title fields.
