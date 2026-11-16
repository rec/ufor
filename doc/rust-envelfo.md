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

## Scores and public parameters

The existing score codec now returns `score::Score`, with `Tuning` and `Envelfo`
variants. `parse_score` takes an explicit preparation limit. `EnvelfoScore` uses
the existing recs/version 4 header, validated name/title/tags and concrete body.
Its public parameters currently bind only the root LFO's rate. Each declaration
must be used, have Hz units and a positive minimum, and contain its default.
Hz public parameters require a seconds-clock LFO, both in the score and at
materialization. Literal beat-clock LFO rates remain supported.

```rust
use std::collections::BTreeMap;
use ufor::codec::{self, Format};
use ufor::envelfo::{Body, ParameterValue, PreparationLimits, Rate, Settings};
use ufor::identifier::Identifier;
use ufor::number::Rational;
use ufor::score::Score;

let limits = PreparationLimits::default();
let score = codec::parse_score(r#"{
  "kind":"envelfo", "name":"motion", "title":"Motion",
  "parameters":{"speed":{"unit":"hz","minimum":0.1,"maximum":10,"default":2}},
  "body":{"kind":"lfo","rate":{"parameter":"speed"}}
}"#, Format::Json, limits)?;
let text = codec::score_text(&score, Format::Toml)?;
assert_eq!(codec::parse_score(&text, Format::Toml, limits)?, score);
let Score::Envelfo(definition) = score else { unreachable!() };
let values = BTreeMap::from([
    (Identifier::new("speed".into())?, ParameterValue::Text("1/3 Hz".into()))
]);
let generator = definition.instantiate(&values, Settings::default(), limits)?;
let Body::Lfo(lfo) = generator.body() else { unreachable!() };
assert_eq!(lfo.rate(), &Rate::Literal(
    Rational::new(3333333333333333, 10000000000000000)?
));
# Ok::<(), ufor::error::Error>(())
```

Instantiation validates finite scalar overrides and declared bounds, rejects
unknown keys, then converts the f64 rate's shortest decimal representation into
a checked exact rational. Thus `0.1` becomes `1/10`, while `1/3 Hz` first rounds
to f64 and becomes the rational shown above. Values whose resulting rational
cannot fit i64 fail explicitly. Root settings/origin replace the score settings;
children inherit the new scope/clock. The score remains unchanged. No reference
resolution or resource access occurs.

Python `instantiate_envelfo(..., context={'portable': True, 'max_records': N})`
revalidates the score and overrides under the same rules. Without portable
context, ordinary authoring retains broader Pint syntax. The checked conversion
and Hz/beat-clock rejection apply to both modes. The operation budget includes
the score's records plus each supplied override.

## Generator-aware binding checks

`samples::bindings::validate_generator_bindings` takes a modulation definition,
bindings, control declarations, generator definitions, event connections and
`PreparationLimits`. Python's corresponding function is
`ufor.samples.processing.validate_generator_bindings`, with keyword
`max_records`. Both share the existing local binding checks, then check generator
existence, selected Patch outputs, scope/domain, shared-child release timing,
releasing envelopes, and known event source ports/destination cues.

```rust
use std::collections::BTreeMap;
use ufor::envelfo::{Generator, PreparationLimits};
use ufor::identifier::Identifier;
use ufor::modulation::Modulation;
use ufor::samples::bindings::validate_generator_bindings;
use ufor::samples::processing::Binding;

let definition: Modulation = serde_json::from_str(r#"{
  "sources":[{"name":"motion","scope":"voice","minimum":-1,"maximum":1}]
}"#)?;
let binding: Binding = serde_json::from_str(
    r#"{"name":"motion","kind":"envelfo","reference":"osc"}"#
)?;
let generator: Generator = serde_json::from_str(r#"{"kind":"lfo","rate":2}"#)?;
let generators = BTreeMap::from([(Identifier::new("osc".into())?, generator)]);
let result = validate_generator_bindings(
    &definition, &[binding], &BTreeMap::new(), &generators, &[],
    PreparationLimits::default(),
)?;
assert!(result.unresolved_bindings().is_empty());
assert!(result.unresolved_connections().is_empty());
assert!(result.unresolved_targets().is_empty());
# Ok::<(), Box<dyn std::error::Error>>(())
```

`BindingValidation` explicitly reports remaining work:

- `unresolved_bindings`, in binding declaration order: followers retain their
  declarations; unresolved score generators carry typed `output` and `domain`
  requirements, plus `release` when voice release timing is requested.
- `unresolved_connections`, in connection order: each connection carries
  `source_port` and/or `destination_cue` requirements for unresolved ends. A
  known end is checked even when the other end is unresolved.
- `unresolved_targets`: all modulation parameter targets, in declaration order.
  Their actual instrument/effect unit, default and capability checks remain external.

An unresolved reference still has a known scope, which must match its use.
Concrete generator sources require exact domains, while derived Patch outputs
permit a declared source domain enclosing the calculated range. Voice release
timing requires a selected releasing Envelope. Full Python `ModulationSettings`
retains its stricter existing behavior for unresolved voice-release references.
This partial API does not claim full settings validation or follower capability.

The aggregate budget counts the supplied context root, embedded modulation root
and all declarations/references once per occurrence. To decode embedded native
modulation above its standalone default, use `Modulation::decode(deserializer,
limits.max_records())` before passing it to this validator. Python propagates
the context override. Standalone constructors, ordinary Serde and the existing
local-only API retain their default limits. Dynamic operation budgets are
semantic validation, not fixed JSON Schema collection maxima.

## Remaining scope

Library resolution remains consumer work. A parsed
unresolved reference does not establish generator existence or its output
domain. Generator state, execution, event replay, smoothing, TempoMap, native
consumer adapters and audio rendering remain in their owning projects. Local
conformance does not establish hosted macOS/Windows/Linux or Rust 1.85 results.
