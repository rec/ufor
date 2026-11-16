# Portable generator definitions

The Rust `envelfo` module provides immutable generator definitions and structural
validation. Python uses its existing models with `context={'portable': True}`.
Both implement the [shared contract](rust-envelfo-contract.md). Enge and enveLFO
remain unchanged; this module does not execute generators or render audio.

Both JSON and TOML preserve declared output order. The TOML parser uses its
approved `preserve_order` feature, with the existing locked dependency versions.

## Native types and validation

`Generator` owns `Settings` and a typed `Body`: `Lfo`, `Envelope`, `Stages`,
`SampleHold`, `Patch` or an unresolved `Reference`. Fields are private; getters
borrow validated values. `Body`, `PatchNode`, `SignalOperation`, `Rate`, `Initial`
and `EnvelopeSegment` allow normal Rust pattern matching. Settings, exact
quantities, markers, definite segments and captured approaches have typed
construction APIs. Other authored definitions can be read through Serde or the
named text adapters.

```rust
use ufor::envelfo::{Body, Generator, PreparationLimits, Rate, Settings};
use ufor::number::Rational;

let generator = Generator::lfo(
    Rate::Literal(Rational::new(2, 1)?),
    Settings::default(),
    PreparationLimits::default(),
)?;
let Body::Lfo(lfo) = generator.body() else { unreachable!() };
assert_eq!(lfo.rate(), &Rate::Literal(Rational::new(2, 1)?));
let reconstructed = Generator::new(
    generator.settings().clone(), generator.body().clone(),
    PreparationLimits::default(),
)?;
assert_eq!(reconstructed, generator);
# Ok::<(), ufor::error::Error>(())
```

Normal `Generator` Serde deserialization validates with the default 10,000-record
budget. `codec::parse_generator(text, format, limits)` accepts an explicit limit
and also enforces document character/value/depth budgets. It checks preparation
size before unit normalization and graph work, then decodes the original text to
retain declared map order. `Generator::new` revalidates reconstruction, including
descendant settings and Patch preparation. There are no unchecked public fields
or global limit settings.

## Patch structure and interchange

Patch supports its existing generator children and Sum, Product, Affine,
Quantize, Latch, Threshold and Slew nodes. Validation checks real signal inputs,
cycles, finite ranges, named outputs, event ports/actions, scopes and child
profiles. Signal dependency order is any valid topological order. Arithmetic
within a node follows its authored input order. Child/output maps use ordered
entries; no alphabetical output order is implied.

```rust
use ufor::codec::{self, Format};
use ufor::envelfo::{Body, PreparationLimits};

let generator = codec::parse_generator(r#"{
  "kind":"patch",
  "envelfos": {
    "a":{"kind":"lfo","rate":"2/s"},
    "mix":{"kind":"sum","inputs":["a","a"]}
  },
  "outputs":{"second":"mix","first":"a"}
}"#, Format::Json, PreparationLimits::new(20_000)?)?;
let Body::Patch(patch) = generator.body() else { unreachable!() };
assert_eq!(patch.outputs()[0].0.as_str(), "second");
let range = patch.signal_ranges().iter()
    .find(|(name, _)| name.as_str() == "mix").unwrap().1;
assert_eq!(range, (-2.0, 2.0));
let text = codec::generator_text(&generator, Format::Toml)?;
assert_eq!(codec::parse_generator(
    &text, Format::Toml, PreparationLimits::default()
)?, generator);
# Ok::<(), ufor::error::Error>(())
```

Child generators inherit clock/scope. Explicit common child fields are rejected,
including explicit defaults and null origins. Canonical parent serialization
omits inherited common fields. A Patch may contain Stages, but cannot contain
another Patch or an unresolved Reference. Stage children remain LFO/Envelope.
Current conservative range and completion-port rules match Python; validation
does not infer tighter ranges from a SampleHold's declared bounds.

## Quantities and pure mathematics

Exact generator rate, phase and duration fields use checked signed 64-bit
rationals. Binary float time and booleans are rejected. Portable scalar fields
use finite f64 values. The approved unit grammar includes reciprocal rates and
exact degree/turn phase conversion; see the contract's spelling table.
Segment duration text requires an explicit seconds/beat suffix. Gate endpoints
retain their boolean representation. Shared Segment and ExponentialApproach
types allow nongenerator levels; envelope polarity restrictions apply only when
those types are used in an Envelope.

```rust
use ufor::envelfo::ExponentialApproach;
use ufor::number::Rational;
use ufor::quantity;

assert_eq!(quantity::exact("90 deg", "phase")?, Rational::new(1, 4)?);
let approach = ExponentialApproach::new(1.0, 0.1, 0.5, 1.0, 0.01, 0.0, 0.0)?;
let segments = approach.resolve(0.0)?;
assert_eq!(segments.len(), 2);
assert_eq!(segments[1].duration(), Rational::new(1, 100)?);
# Ok::<(), ufor::error::Error>(())
```

Captured-approach resolution checks finite intermediates and rounds derived
durations once to nanoseconds using ties-to-even. Nanosecond counts must fit i64.
Python's shared helper uses the same checks, including for nongenerator callers.
Quantization rounds halfway grid coordinates toward the higher point. Neither
helper is a generator runtime. Slew rates are f64 quantities and retain finite
values such as `1e-200/s`; exact-rational time limits do not apply to them.

## Python portable validation

```python
from ufor.envelfo import LFO

generator = LFO.model_validate(
    {'rate': '2/s', 'phase': '90 degrees'},
    context={'portable': True, 'max_records': 20000},
)
```

The context propagates through nested definitions. Existing instances are
revalidated from actual field values, preserving invalid edits for rejection.
Inherited child values are checked against the parent before omitting their
common fields from the validation input. Stored serialization caches are not
trusted. Ordinary authoring retains existing coercions and broader Pint syntax;
normalized authoring instances can subsequently cross the portable boundary.

Portable identifiers use the pinned Unicode repertoire shared with modulation.
Counters require signed 64-bit integers, excluding bool/float/string coercions;
boolean fields require booleans. Origin identities, path/selector references,
transition events and event-port strings are bounded at 4,096 characters.
Selectors are bounded before canonicalization. Descriptions retain the overall
document budget. No path resolution or platform-specific filesystem operation
occurs during validation.

## Remaining scope

Native `envelfo` score headers, public-parameter instantiation, library resolution
and generator-aware modulation binding checks remain later stages. A parsed
unresolved reference does not establish generator existence or its output
domain. Generator state, execution, event replay, smoothing, TempoMap, native
consumer adapters and audio rendering remain in their owning projects. Local
conformance does not establish hosted macOS/Windows/Linux or Rust 1.85 results.
