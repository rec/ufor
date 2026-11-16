# Rust EnveLFO definitions and validation

## Goal and ownership

Port the portable generator definitions and their structural validation to the
existing `ufor` Rust crate, following [the modulation port](rust-modulation.md).
The end goal remains a library usable from Rust and Python with matching format
semantics and idiomatic facilities in each language.

Implementation was authorized on 2026-11-15. All seven recommendations were
approved, with a configurable preparation-record limit defaulting to 10,000.
The quantity syntax, per-operation configuration and captured indefinite-hold
alignment described below were subsequently approved as well.

The implementation now supplies the
[contract inventory](../doc/rust-envelfo-contract.md),
[API guide](../doc/rust-envelfo.md), shared cases and independent Python/Rust
consumers. Native generator models and Python portable alignment include
LFO/Envelope/SampleHold, Stages/Patch, unresolved references, exact units,
configurable preparation limits and supporting pure mathematics. Native score
adapters/public-parameter instantiation, generator-aware binding checks and
hosted qualification remain below. Standalone preflight helpers still count
records only; the model/parser boundary performs structural validation as well.

On 2026-11-16 the user approved TOML's `preserve_order` feature in a separate
dependency commit. It activates the already locked `indexmap` package (Rust
1.85) without changing versions. Ordered-document cases check the parser and
writer together. No implementation decisions are currently pending.

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

### Completed: inventory, native definitions and Python alignment

The contract inventory and `conformance/envelfo-definitions.json` are tracked.
`test/test_envelfo_conformance.py` and `crates/ufor/tests/envelfo.rs` check
definitions, normalized values, structural failures, quantities, budgets,
inheritance, output order and pure helper results. Execution fixtures remain in
enveLFO. The native public types have private fields and immutable accessors;
Serde and named generator adapters validate whole definitions.

Keep uFor and enveLFO independently testable from their declared checkouts and
dependencies. Do not require a sibling repository at test time or copy its
runtime corpus wholesale into uFor.

Python portable validation propagates its context and configured record budget,
revalidates actual instance field values, checks inherited values before
omitting them, and retains ordinary authoring coercions. Shared Segment and
ExponentialApproach callers keep nongenerator level ranges. Captured resolution
now rejects nonfinite intermediates and derived nanosecond counts outside i64.

LFO, Envelope, SampleHold, Stages, Patch nodes/connections and unresolved
reference definitions are implemented natively. Definitions preserve the
current scope, range, completion-port, inheritance and serialization rules.
Signal dependency order is unconstrained between independent nodes; input-list
arithmetic and public output order are preserved. Reference validation reads no
resources. Generic JSON maps are used for preflight counts, not for retaining
authored order in typed parsing.

Local verification on 2026-11-16 passed: 2,151 Python tests with one skip,
34 Rust integration tests and six Rust documentation examples. Ruff, formatting,
type checking, pyupgrade, Clippy and diff checks passed. These results use the
installed non-editable Python package and locked Cargo workspace; hosted
platform/minimum-compiler evidence remains below.

### Remaining: scores, parameters and generator-aware binding checks

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

### Remaining: score/binding documentation and hosted qualification

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

## Approved decisions

The prior approval to use 64-bit numbers remains in force. The following
recommendations are approved; they do not reopen that policy.

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
7. **Limits and ordering.** Use a configurable preparation budget, default 10,000,
   counting generators, segments, markers, stages, transitions, Patch nodes,
   input references, output entries, connections, parameters and supplied binding
   context once per occurrence. Reuse 4096-character identifier/quantity limits
   and existing document budgets. Specify any additional free-text/reference
   limits before implementation. Keep declaration order for public outputs and
   authored arithmetic order; do not make an arbitrary topological order part of
   the wire contract.

Approved implementation details:

- The record override is per operation: Python portable validation context
  `max_records`, and an explicit Rust preparation limit. Constructors and normal
  Serde validation default to 10,000. No process-global state or score field.
  Generator-aware checks count embedded modulation in the same budget; existing
  standalone modulation APIs retain their defaults. Text/document limits remain.
- Quantity syntax uses the existing seconds/beats and Hz aliases, phase aliases
  turn/turns/cycle/cycles and deg/degree/degrees, and reciprocal rate spellings
  such as `1/beat`, `2/beat`, `1/s` and `2 Hz`. Bare rational text is valid for
  rate/phase; serialized Segment durations retain explicit `s` or `beat` units.
- An Envelope with `initial='current'` and only indefinite holds is valid as a
  noninitial stage. Fix the empty-level validation crash. Existing initial-stage
  and top-level binding restrictions remain in force.
- Origin identities, paths, selectors, event-port strings and transition-event
  strings are capped at 4096 characters. Selector input is checked before
  canonicalization. Descriptions retain the overall document budget.

Ask immediately if implementation reveals another behavior, data-shape or
ownership decision. Record approvals here and in the shared cases before coding
the affected behavior.

## Deferred work

No enge or enveLFO changes, additional dependencies beyond the approved TOML
order-preservation feature, runtime adapters, native host
integration, generator execution, random streams, snapshots, state/event replay,
control smoothing runtime, TempoMap/transport execution, audio generation,
Python/Rust bindings, device access or WebAssembly are included. Runtime
allocation/performance claims require separate consumer qualification.

## Additional work beyond the prompt

None.
