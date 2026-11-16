# Rust EnveLFO contract inventory

This inventory accompanies [the implementation plan](../plan/rust-envelfo.md).
It records the implemented generator, score and partial binding contract.
Enge and enveLFO are unchanged. No generator runtime is
implemented here. See [the native/Python API guide](rust-envelfo.md).

## Current implementation and evidence

`conformance/envelfo-definitions.json` version 1 contains definition, exact
quantity, record-budget, quantizer, captured-approach, ordered-document and
portable-boundary cases. The Python consumer is
`test/test_envelfo_conformance.py`. Rust's `crates/ufor/tests/envelfo.rs` currently
consumes the shared definition and preparation cases, including strict types,
inheritance, ranges, units, limits and JSON/TOML semantic round trips. Native
generator models and definition interchange are implemented. The additional
`conformance/envelfo-scores-bindings.json` cases are consumed by that Python test
module and `crates/ufor/tests/envelfo_scores.rs`. They cover score headers,
parameters, materialization, known binding facts, typed unresolved requirements,
event connection quantities and declaration order.

Python's `modulation_contract.exact_quantity` and Rust's `quantity::exact` share
the exact generator quantity grammar. Existing nonnegative smoothing APIs reuse
this arithmetic while keeping their own domain checks. Python's
`envelfo_contract.preparation_records` and Rust's `envelfo::preparation_records`
implement the same configurable preparation preflight. The standalone functions count
decoded declarations; they do not validate a generator's structure, references,
field domains or document budgets. They are not substitutes for the
validated model/parser boundary. The `Generator` boundary and Python portable
models now combine this preflight with structural validation.

The approved Python fix permits `initial='current'` with only indefinite holds
without taking the minimum of an empty level list. A noninitial Stage may use
that envelope. Initial-stage, Patch-child and top-level bound-envelope rejection
remain separate contextual checks. Shared cases exercise the stage distinction.

## Definition inventory

| Definition | Defaults and important constraints |
|---|---|
| Common generator | Voice scope, seconds clock, elapsed position driver, no origin. The shared base itself is not concrete. Transport position requires a beat-clock transport-reset LFO without delay/fade, or an unresolved reference with a compatible profile. |
| LFO | Required nonnegative exact rate or public parameter reference; sine, phase 0, duty 1/2, trigger reset, delay/fade 0, center 0, depth 1, no markers. Phase is [0,1), duty [0,1], center/depth remain within [-1,1]. Marker names are unique and positions below 1. Shapes are sine, square and triangle. |
| Envelope | Required nonempty segments, initial 0, activation start, unipolar, hold true, current retrigger, once playback. Release/markers are empty; loop names/repeat count absent. Levels match polarity. Definite segments, indefinite holds and captured approaches are distinct variants with different playback restrictions. |
| SampleHold | Voice only; minimum -1, maximum 1, ordered within [-1,1]. Its definition does not include a random stream or state. |
| Stages | Required initial stage and nonempty named stages, no transitions by default. Children are LFO or Envelope; clock/scope are inherited. Initial capture, child public rate references, child release and event-start envelopes are forbidden. Child Envelope needs positive duration or an indefinite hold. |
| StageTransition | Nonempty `from` list, event and enter/finish action. Python also accepts `from_stages`; canonical output uses `from`. Validate actual stage/marker/cue ports, completion rules and reserved names. |
| Patch | Required child map and named output map; no event outputs/connections by default. Children include Stages and the signal nodes below, but no nested Patch or unresolved reference. |
| Signal nodes | Sum/Product require at least two ordered inputs. Affine defaults scale 1/offset 0. Quantize requires positive step, origin 0, ties toward the higher grid point. Latch has one input. Threshold requires lower < upper. Slew requires nonnegative rise/fall and optional initial. |
| PatchEventConnection | Source/target required; action start, every 1, offset 0, probability 1, exact seconds delay 0. Only cue actions carry a cue name. Target compatibility depends on the actual child definition. |
| EnveLFOReference | Exactly one existing ScoreReference path or selector, empty parameter overrides, no materialized origin. Parsing never resolves the reference or reads files. |
| EnvelfoScore | Existing recs/version 4 header, kind envelfo, no parameters by default. Concrete body only. Public parameters currently bind only the root LFO rate and require Hz units. Unused/missing parameter declarations fail. |

Origin metadata has an identity string and optional lowercase 64-digit SHA-256.
It is provenance, not proof that a resource has been fetched or verified. A score
reference uses the existing relative POSIX path/selector grammar, including
canonical selectors and optional hashes; do not invent an asset lookup protocol.

## Inheritance and serialization

Children inherit parent clock and scope. Explicit child clock, scope,
position_driver or origin fields are rejected, including explicit default values.
Canonical parent serialization omits these fields from child objects. Preserve
that distinction when revalidating model instances and round-tripping documents.

Segment duration serializes with an explicit `s` or `beat` suffix. The internal
`duration_unit` is omitted. Integer/Fraction authoring values default to seconds;
authored unit suffixes determine the clock and must agree with a supplied unit.
Boolean segment endpoints remain gates, not coerced numbers. Shared Segment and
ExponentialApproach helpers also serve nongenerator callers; envelope polarity
constraints must not leak into those callers.

## Exact quantity contract

Both implementations use signed i64 numerators and positive i64 denominators,
with checked 64-bit arithmetic, reduction and explicit errors. Intermediates do
not gain arbitrary precision or i128 fallback. Both crates' rational storage
bounds agree; enveLFO's wider intermediate calculations are outside this port.

The grammar consists of signed decimal/scientific literals and rational
quotients, with at most one compatible unit factor. The unit may follow the
numeric quantity before or after further numeric divisors. Bare compatible units
mean one unit, following the existing modulation grammar. Parentheses, addition,
multiplication, powers and functions are unsupported. Inputs are integer values,
exact rational text, or already validated Python Fractions; binary float time and
booleans fail. A mathematical helper may return a negative quantity; the field
using it applies its own nonnegative or normalized domain.

| Quantity | Spellings |
|---|---|
| Seconds | s, second, seconds, ms, millisecond, milliseconds |
| Beats | beat, beats |
| Hz | Hz, hertz, kHz, kilohertz, mHz, millihertz, MHz, megahertz; reciprocal seconds spellings such as `2/s` and `1/ms` |
| Cycles per beat | Reciprocal beat spellings such as `2/beat` and `1/4/beats` |
| Phase in turns | turn, turns, cycle, cycles, deg, degree, degrees; degrees divide by 360 |
| Ratios | Numeric text only |

Bare rational text is accepted by the quantity helper. Segment's field-level
requirement for an explicit unit on textual durations is separate. Seconds and
beats never convert without external clock context. Radians are not an exact
phase spelling because conversion would involve pi.

`per_second` is the exact helper's reciprocal-second quantity, also accepting Hz
spellings. Slew fields ultimately need finite f64 rates, not exact times; their
portable model integration must preserve that distinction and must not impose
exact-rational bounds on arbitrary finite scalar rates.

## Preparation budget

The budget is per operation, default 10,000. Python accepts a nonnegative signed
64-bit integer maximum. Rust `PreparationLimits::new` accepts a platform-sized
nonnegative count within the signed 64-bit domain. Zero is valid configuration;
it rejects every nonempty record set. Raising the limit permits larger graphs;
it does not change text, document-value or nesting limits.

The decoded preflight counts:

- One for the supplied root record. A score or combined binding context counts
  its root wrapper once, then counts contained records.
- Each generator, segment, marker, stage wrapper, transition, Patch node,
  parameter declaration, binding, control declaration, modulation source, route
  and mapping point once, where declared.
- Each item in input and transition-source lists once, including repeated
  references. Each named signal/event output entry counts once.
- Nested generator bodies, stage bodies and embedded modulation roots once.
  Scalar fields, embedded target/action/parameter-reference objects, tags and
  origin metadata do not add records. The independent document budget bounds
  their decoded size.

Map containers themselves do not add records. A Patch child that is a generator
is one record, not both a generator and another node. References never expand the
referenced definition. The shared corpus specifies worked counts for roots,
segments, shared Patch nodes, stages, scores and combined binding contexts.
Collection sizes are checked before adding their members to preparation work.

Python `context={'portable': True, 'max_records': N}` and Rust's explicit
`PreparationLimits` apply to one whole generator validation operation. Raising
the limit works through nested generator definitions and model revalidation.
Generator-aware binding validation combines its supplied modulation,
bindings, controls, generators and event connections in that same operation budget.
Model instances and decoded objects receive the same record counts. Existing standalone
modulation APIs retain their default. No limit field belongs in score data.

## Range and contextual boundaries

Preserve authored input-list arithmetic order. Patch signal order is any valid
dependency order; independent nodes have no required relative order. Public
output enumeration follows declaration order. Rust uses ordered entries and
Serde map visitors for generator maps. Named adapters decode the original text
after budget checks, rather than reusing a sorted generic JSON map. TOML also
requires its parser's `preserve_order` feature to retain declared table order.

Current Python signal ranges conservatively give ordinary generators [-1,1],
except unipolar Envelope [0,1]. In particular, SampleHold's narrower declared
range does not currently narrow Patch range propagation. Preserve this existing
validation behavior, rather than silently tightening it during the port.

Binding validation similarly distinguishes exact generator source-domain
matching from enclosing-domain checks for derived Patch outputs. Resolve actual
Patch outputs, scope, release timing and event ports. Leave follower processor
capabilities and instrument/effect target-unit/default compatibility explicitly
unresolved until their owning definitions are supplied. Do not claim full
ModulationSettings validation or implement placeholder processor/generator data.

## Score and binding boundary

Native score parsing returns the typed `score::Score` enum. Its supported kinds
are tuning and envelfo; `parse_score` requires an explicit preparation limit.
Direct typed deserialization retains the default 10,000 limit. Concrete EnveLFO
score bodies cannot be unresolved references. Public parameters currently bind
only root LFO rates and must be declared in Hz with a strictly positive minimum.
Hz parameter use on a beat-clock LFO is rejected, including when a caller
requests that clock during materialization. Literal beat-clock LFOs remain valid.

Overrides normalize to finite f64 within declared bounds, then the shortest
decimal spelling becomes a checked i64 rational rate. Unknown overrides and
unrepresentable exact results fail. The budget counts supplied overrides as well
as score records. Materialization replaces root settings/provenance and inherits
scope/clock into children without mutating the score or resolving resources.

The partial generator-aware validator returns typed output/domain/release checks
for unresolved score references. Known scopes are checked immediately. Event
connections retain source-port/destination-cue checks only for unresolved ends;
known ends must be valid. Followers and all target-setting compatibility remain
explicitly unresolved. Full Python settings retain their existing stricter
unresolved voice-release checks. See the [API guide](rust-envelfo.md) for signatures,
ordering and exact result shapes exercised by shared cases.

## Remaining qualification

Portable model alignment, native LFO/Envelope/SampleHold, Stages/Patch,
unresolved-reference definitions and the supporting pure mathematics are
implemented, together with native scores/public parameters and generator-aware
partial bindings. Hosted platform qualification remains; current local success does not establish
consumer execution, reference resolution or full contextual validation.
