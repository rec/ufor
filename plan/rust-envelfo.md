# Rust EnveLFO definitions and validation

## Goal and ownership

Port the portable generator definitions and their structural validation to the
existing `ufor` Rust crate, following [the modulation port](rust-modulation.md).
The end goal remains a library usable from Rust and Python with matching format
semantics and idiomatic facilities in each language.

This document authorizes no implementation by itself. The stages below are
planned work; the recommendations under decisions are not yet approved.

**Keep enge unchanged.** Do not change its source, dependencies, lockfiles,
interfaces, plans, fixtures, preparation arrays or runtime. Treat current enge
and enveLFO sources as read-only evidence. Consumer integration is later work.
Stop and identify any dependency on changes to either project before proceeding.

| Project | Responsibility |
|---|---|
| uFor | Authored definitions, units, interchange, structural validation and pure format mathematics |
| enveLFO | Normalized execution definitions, state transitions, generator/Patch execution and continuation |
| enge | Audio preparation, indexed runtime plans, audio rendering, storage and callback behavior |
| Hosts | Transport, clock observations, instance ownership and application policy |

Do not duplicate the enveLFO runtime in uFor. The first useful deliverable is
native validation of LFO/envelope documents. The complete milestone additionally
allows Rust to inspect actual generator definitions when checking bindings that
the current `validate_local_bindings` returns as unresolved.

## Contract inventory

Start from current code rather than assuming all Python helpers belong in Rust:

- `ufor/envelfo.py`: inherited clock/scope settings, generator profiles, LFO,
  Envelope, Stages, SampleHold, Patch nodes, markers, event connections, public
  parameters, references, score envelopes and instantiation.
- `ufor/segments.py`, `ufor/envelope.py`, `ufor/approach.py`, `ufor/lfo.py`:
  durations, definite/indefinite segments, captured approaches, curves, reset and
  retrigger enums, and the pure calculations required by definition validation.
- `ufor/control.py`: clock/scope/polarity definitions and exact quantities needed
  by generators. This is not authorization to port TempoMap or transport runtime.
- `ufor/samples/processing.py`: generator binding domains/scopes, Patch output
  selection, voice release timing and event connection checks. Separate these
  from validation requiring real instrument/effect target settings.
- Existing Rust `number`, `quantity`, `identifier`, `modulation` and codec modules:
  reuse their validated boundaries rather than adding parallel numeric types.
- Read-only references in enveLFO: `envelfo-core` definitions and the existing
  `envelfo-runtime.json`, `envelfo-patch.json` and `captured-envelope.json` corpora.
  Enge's `enge/envelfo_graph.py` and native preparation show consumer needs; they
  do not define a new portable format.

Record defaults, accepted wire shapes, inherited versus explicit fields,
serialization omissions, validation dependencies, scalar operation order and
numeric bounds. Flag discrepancies before choosing behavior. Existing Python
acceptance is evidence, not automatic approval to preserve an accidental bug.

## Implementation stages

### 1. Inventory and executable contract

Resolve the decisions below before Rust implementation. Add
`conformance/envelfo-definitions.json` and a focused Python fixture consumer.
Define expected normalized documents and error categories from the contract,
not by blindly recording Python output. Identify which existing enveLFO fixtures
test execution and must stay with that project.

Keep uFor and enveLFO independently testable from their declared checkouts and
dependencies. Do not require a sibling repository at test time or copy its
runtime corpus wholesale into uFor.

### 2. Supporting types and portable Python boundary

Implement the required clock/playback/reset/retrigger types, exact quantities,
markers, segment variants and captured-approach definitions. Reuse checked
64-bit rationals and the pinned portable identifier repertoire.

Align affected Python models using `context={'portable': True}` and instance
revalidation, following the tuning/modulation approach. Preserve ordinary Python
authoring facilities where they normalize to valid portable definitions.
Review shared Segment/Curve/ExponentialApproach callers before changing them;
do not silently impose generator-only level ranges on other users.

### 3. LFO, Envelope and SampleHold

Port validated immutable Rust definitions and Serde interchange, including
literal/public-parameter rate alternatives, scope/clock/position-driver rules,
markers, polarity, onset/release segments, holds, retrigger behavior, playback
modes, loop boundaries and repeat counts. Include SampleHold's definition and
scope/range rules without implementing its random stream.

Validate inherited fields and preserve the existing omission of inherited
settings on child serialization. Do not expose invalid editable Rust fields.
Implement only the pure helpers explicitly selected under decision 5.

### 4. Stages and Patch structure

Port stage actions/transitions and all currently supported Patch child types:
LFO, Envelope, Stages, SampleHold, Sum, Product, Affine, Quantize, Latch,
Threshold and Slew. Nested Patch support must follow the actual Python type
contract; do not add recursion absent from it.

Check stage names, initial stage, transitions, completion/marker ports, inherited
settings, allowed child profiles and reserved names. For Patch, validate signal
references and acyclicity, calculate finite signal ranges, resolve selected
outputs and event outputs, and check event action/cue compatibility. Preserve
input-list arithmetic order and distinguish signal dependency cycles from event
connections; do not invent an event-cycle rejection policy.

### 5. Scores, parameters and generator-aware binding checks

Add the existing `envelfo` score envelope to native codec handling, including
public parameter declarations, parameter substitution and origin metadata.
Represent unresolved score references as references, not fabricated generators.
Reference parsing and instantiation must not read files, fetch assets or invoke
an application. Define score-reference support using the actual existing schema.

Add a separate generator-aware check alongside `validate_local_bindings`, sharing
its checks. Supply real generator definitions and validate generator existence,
selected Patch outputs, source scope/domain, consistent release timing for shared
Patch children, releasing-envelope requirements, and generator event ports/cues.
Preserve existing asymmetric domain rules unless a decision explicitly changes
them. Success must not imply follower processor capability or instrument/effect
target validation. Retain explicit unresolved results for missing external
context; do not construct a partly validated full `ModulationSettings` model.

### 6. Documentation and qualification

Update the native API guide, format/validation documentation and generated schema
where the approved implementation changes them. Include tested Rust examples
for a simple generator, a Patch, a score round trip and binding validation.
Replace completed plan stages with evidence and remaining work.

Run the affected Python suite and repository Python verification gates when
Python/data changes occur. Test the installed non-editable package, including
resource packaging. Run locked Cargo tests, rustfmt and Clippy. Preserve Rust
1.85 and Python 3.13 compatibility, and platform-neutral code for macOS, Windows
and Linux. Hosted evidence comes from the existing release matrix; do not run
release workflows for every commit or claim local checks qualify other systems.

## Shared conformance cases

Use a versioned language-neutral JSON corpus consumed independently by Python
and Rust. Exact rationals, integers, enums, identifiers and reference selections
compare exactly. Finite scalar calculations use explicit `1e-12` absolute and
relative tolerances unless a case requires an exact rounding assertion. Compare
semantic round trips rather than JSON/TOML text layout or error message wording.

| Area | Required cases |
|---|---|
| Common definitions | Defaults, unknown fields, kind discriminators, strict portable booleans/numbers, pinned Unicode boundaries, origin hash format and nested instance revalidation |
| Exact quantities | Integer/rational/decimal/scientific spellings; seconds/beats/rates/phase; incompatible units; bool/float-time rejection; zero denominator, signed limits and intermediate overflow |
| Inheritance | Parent scope/clock propagation, forbidden explicit child overrides, serialization omission and round trips without accidental overrides |
| LFO | Shapes, zero rate, phase and duty endpoints, center/depth limits, marker uniqueness/positions, transport-driver restrictions and unsupported inline parameter references |
| Envelope | Polarity bounds, empty segments, zero durations, indefinite holds, release, current-level initialization, loop marker pairs/order, repeat counts and captured-approach restrictions |
| Pure helpers | Quantizer positive/negative ties and finite range endpoints; captured-approach threshold/reachability, minimum durations/distances and nanosecond rounding if included |
| Stages | Duplicate/unknown stages, initial capture rejection, transition aliases, cue/stage ports, reserved names, finite/infinite loop completion and disallowed child profiles |
| Patch signals | Every node kind, missing inputs, self/multi-node cycles, shared dependencies, range propagation, quantizer ties, finite overflow, selected output references and scope restrictions |
| Patch events | Marker/stage/threshold ports, start/cue/sample/capture targets, cue payloads, every/offset/probability/delay boundaries and event-output references; no execution traces |
| Scores | Existing headers, parameter use/units/bounds, defaults/overrides, unknown parameters, materialization metadata, unresolved references and JSON/TOML semantic round trips |
| Bindings | Missing generators, non-Patch output selection, Patch output names, exact versus enclosing domain rules, scope mismatch, shared-child release conflicts, valid releasing envelopes and unresolved external facts |
| Budgets | At/beyond text, aggregate-record, nesting and document limits; large input/reference lists counted before graph work; no recursion or expansion bypass |

Assert graph dependency constraints and derived ranges without requiring an
arbitrary total order between independent nodes. Add order-sensitive arithmetic
cases where authored input order affects floating-point results. Record any
Python alignment that affects existing consumers as a deliberate contract change.

## Decisions before implementation

The prior approval to use 64-bit numbers remains in force. These recommendations
need approval; they do not reopen that policy.

1. **Milestone scope.** Recommend all current concrete generator definitions,
   score/parameter/reference structures and generator-aware checks, delivered in
   the stages above. This avoids declaring an unsupported partial schema to be
   complete. A smaller LFO/envelope-only milestone is possible, but Patch binding
   resolution would remain unavailable until later.
2. **Python alignment.** Recommend the existing portable validation context and
   revalidation approach for the affected generator types, while retaining broad
   authoring syntax. Review shared helpers before imposing stricter limits;
   unrelated Scale, oscillator, lighting and audio behavior stays outside scope.
3. **Numeric compatibility.** Recommend uFor's existing checked 64-bit arithmetic
   with explicit overflow errors, no i128 fallback or arbitrary precision. Both
   native crates store signed i64 numerators and positive i64 denominators;
   `envelfo-core` currently uses i128 intermediates, so accepted arithmetic can
   differ even with identical storage bounds. Do not require identical overflow
   acceptance or change either project's arithmetic to hide that difference.
4. **Units.** Recommend extending the approved flat quotient grammar only for
   exact beat durations, cycle rates and phase, plus scalar Slew rates, using the
   actual generator clock contract. Inventory and approve the precise alias and
   reciprocal-unit table first. Preserve Segment's explicit unit serialization;
   never infer seconds from a beat quantity or use tuning pitch expressions as a
   general time parser. This is more predictable than exposing all Pint syntax.
5. **Pure mathematics versus runtime.** Recommend porting quantization and signal
   range calculation, which validation requires, plus captured-approach segment
   resolution with its existing nanosecond rounding. Defer standalone Curve
   playback, activation observations, event/state models and generator execution.
   This supplies useful definition mathematics without a second runtime.
6. **Binding API and external context.** Recommend a separate generator-aware API
   using real definitions, preserving the existing local API and returning typed
   unresolved external facts. Fix the exact signature and result shape during
   inventory. Do not add an execution adapter or depend on `envelfo-core` in this
   milestone; later adaptation belongs with the consumer. Full target/follower
   validation needs the corresponding instrument/effect definitions later.
7. **Limits and ordering.** Recommend a shared 10,000-record preparation budget
   counting generators, segments, markers, stages, transitions, Patch nodes,
   input references, output entries, connections, parameters and supplied binding
   context once per occurrence. Reuse 4096-character identifier/quantity limits
   and existing document budgets. Specify any additional free-text/reference
   limits before implementation. Keep declaration order for public outputs and
   authored arithmetic order; do not make an arbitrary topological order part of
   the wire contract.

Ask immediately if implementation reveals another behavior, data-shape or
ownership decision. Record approvals here and in the shared cases before coding
the affected behavior.

## Deferred work

No enge or enveLFO changes, new dependencies, runtime adapters, native host
integration, generator execution, random streams, snapshots, state/event replay,
control smoothing runtime, TempoMap/transport execution, audio generation,
Python/Rust bindings, device access or WebAssembly are included. Runtime
allocation/performance claims require separate consumer qualification.

## Additional work beyond the prompt

None.
