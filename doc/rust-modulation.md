# Portable modulation and control declarations

Python and Rust implement the same modulation definitions and scalar reference
contract. The native crate now supplies `modulation`, `control`, `identifier`,
`quantity`, `samples::controls` and `samples::processing` modules. Enge integration,
audio rendering and generator execution are separate work; no enge changes were
made for this port.

## Definitions and validation

The Rust `modulation` module provides `Unit`, `Operation`, `Interpolation`,
`SourceScope`, `Target`, `Parameter`, `Source`, `Point`, `Route`, `Modulation`,
`SourceValue` and `ParameterValue`. `control::Scope` has voice, instrument and part
variants; source scope additionally permits trigger. `control::Polarity` and
`samples::controls::ControlDeclaration` define unipolar and bipolar controls.

Validated constructors and Serde deserialization enforce finite scalars,
identifier rules, domains, point ordering, uniqueness, source/target references,
matching units and the existing scope restriction for instrument parameters.
Fields are private in Rust; getters expose immutable values and edits construct
new validated definitions. Python collections remain editable, with instance
revalidation at portable validation and enclosing-model boundaries.

Python uses `context={'portable': True}` with `model_validate` or
`model_validate_json`, including nested definitions and score-codec validation.
Scalar numbers accept integer and floating JSON spellings, excluding booleans,
nonfinite values and numeric strings outside the approved quantity fields.
Ordinary Python construction retains its authoring coercions and broader Pint
syntax, which must normalize to portable values before interchange.

## Mapping and combination

`map_value` clamps outside the knots. Linear interpolation, a step changing at
the knot, exponential interpolation and single-point constant mappings are
supported. Source-domain rejection is a separate evaluator check. Supplied unused
sources are still validated; unused declared sources need not be supplied.
Routed sources must be present, and base overrides must be known, unique and in
their parameter domains.

Routes reduce in `(source ID, route ID)` order. Mapping precedes weighting:
additions become `w*a`, and multipliers become `1+w*(m-1)`. The result is
`(base + sum(additions)) * product(multipliers)`, with the base outside the sum.
The Rust f64 partial-sum implementation preserves cancellation and halfway
rounding cases covered against Python's `math.fsum`. Products retain route order.
F64 rounding in the weighting expression is preserved, including a sufficiently
tiny multiplier rounding to zero. No algebraic regrouping or clipping is applied.
Results retain parameter declaration order. Nonfinite scalar inputs, arithmetic
overflow and out-of-domain final results fail deliberately.

```rust
use std::collections::BTreeMap;
use ufor::codec::{self, Format};
use ufor::identifier::Identifier;
use ufor::modulation::{evaluate, SourceValue};

let definition = codec::parse_modulation(r#"{
  "parameters": [{"target":{"name":"gain","parameter":"amount"},
    "unit":"db","scope":"voice","minimum":-60,"maximum":12,"default":0}],
  "sources": [{"name":"wheel","scope":"voice","minimum":0,"maximum":1}],
  "routes": [{"name":"wheel_gain","source":"wheel",
    "target":{"name":"gain","parameter":"amount"},"operation":"add","unit":"db",
    "points":[{"input":0,"amount":0},{"input":1,"amount":6}]}]
}"#, Format::Json)?;
let values = BTreeMap::from([
    (Identifier::new("wheel".into())?, SourceValue::new(0.5, 1.0)?)
]);
assert_eq!(evaluate(&definition, &values, &[])?[0].value(), 3.0);
let text = codec::modulation_text(&definition, Format::Toml)?;
assert_eq!(codec::parse_modulation(&text, Format::Toml)?, definition);
# Ok::<(), ufor::error::Error>(())
```

The text adapters operate on supplied UTF-8 strings. Standalone leaf types also
support normal Serde JSON/TOML use. Modulation is embedded data, not a new score
kind; there is no modulation score envelope or format-version change.

## Scalar quantities and exact smoothing

Portable quantity text accepts signed decimal/scientific literals and rational
quotients, with at most one compatible unit factor. A unit can follow a numeric
quantity before or after its quotient; a bare unit means one unit. Examples are
`1 kHz / 3`, `1/4 beat`, `250 ms` and `500 mV`. Leading unit factors followed by
numbers, unit-only denominators, parentheses, addition, multiplication, powers
and functions are outside this grammar. The tuning expression grammar is unchanged.

| Declared unit | Portable spellings |
|---|---|
| `hz` | Hz, hertz, kHz, kilohertz, mHz, millihertz, MHz, megahertz |
| `cents` | cent, cents, musical_cent, semitone, octave, oct |
| `db` | dB, decibel, decibels |
| `volts` | V, volt, volts, mV, millivolt, millivolts |
| `seconds` | s, second, seconds, ms, millisecond, milliseconds |
| `beats` | beat, beats |
| `radians` | rad, radian, radians |
| `logical`, `ratio`, `normalized` | Numeric text only |

Scalar quantities use f64 arithmetic and can represent finite scientific values
outside the exact pitch-rational domain. Smoothing is different: it is an exact,
nonnegative rational second quantity, default `1/200`. Portable smoothing accepts
integer values or rational/decimal/scientific strings with optional second units,
not binary float times or beat/frame conversion. Components and intermediates use
the checked i64/u64 policy, with no i128 or arbitrary-precision fallback.

## Binding cutline

`samples::processing` supplies `EventBinding` (key or velocity), `ControlBinding`,
`GeneratorBinding`, `FollowerBinding`, `ReleaseTiming` and the discriminated
`Binding` enum. Parsing a generator/follower leaf validates its fields, not the
referenced generator or processor.

`validate_local_bindings` takes a modulation definition, binding list and actual
control declarations. It checks:

- Binding names are unique and match the source names exactly.
- Key and velocity sources are voice scoped; velocity has domain `[0,1]`.
  Key source bounds and mapping inputs are integer-valued.
- Control references exist, their source domain exactly matches unipolar `[0,1]`
  or bipolar `[-1,1]`, and the source is not voice scoped.
- Follower sources are voice scoped with minimum zero.
- The combined preparation record count is within the limit.

The return value is the generator/follower declarations still requiring external
resolution, in binding declaration order. Rust returns typed `UnresolvedBinding`
variants; Python returns the corresponding binding models. An empty result means
no such references remain, not that all instrument or processor settings have
been validated. In particular, this API does not establish generator existence,
Patch output validity, release-envelope behavior, follower processor support,
event ports/cues, or target-setting unit/default compatibility.

`ModulationSettings`, control-ramp execution, clocks/tempo maps, generator state
and full instrument/effect documents have not been ported by this milestone.
Their existing Python validation and execution stay in their owning modules.

## Limits and Unicode

Preparation permits at most 10,000 aggregate parameters, sources, routes, points,
bindings and control declarations. A standalone route counts itself and its
points; local binding validation additionally counts its supplied bindings and
control declarations. Identifier and quantity text limits are 4096 characters.
The named text adapters independently retain the existing 16,777,216-character,
100,000-value and 64-level document limits.

Portable modulation identifiers use Python 3.13 / Unicode 15.1.0's single-character
Lowercase and Decimal/Digit behavior, plus `-` and `_` after the first character.
There is no normalization or case folding. Generated range tables keep Rust
independent of its compiler's Unicode tables and require no Python at runtime.
Python authoring keeps native Unicode behavior, while portable validation uses
the pinned repertoire. Other uFor identifier domains have not been migrated to
this pinned policy by this port.

Regenerate the checked-in Python JSON resource and Rust range source together:

```sh
uv run --python 3.13 --frozen --no-editable python schema/generate_identifiers.py
cargo fmt --all
```

The generator, outputs and provenance are tracked in the repository. Shared
fixtures are in `conformance/modulation.json`, consumed by
`test/test_modulation_conformance.py` and `crates/ufor/tests/modulation.rs`.
They cover normalized definitions, both interchange formats, mapping boundaries,
combination/order/cancellation, units, exact smoothing, identifiers, binding
resolution status and preparation boundaries. Local results do not establish
minimum-compiler or hosted Windows/Linux/macOS qualification; those checks stay
in the release workflow.
