# Rust implementation

The Cargo workspace implements checked pitch numbers, expression evaluation,
`Computed`, `RatioTable`, `IntervalPattern`, `FrequencyTable`, `Tuning`, and the
`TuningScore` envelope in `crates/ufor`. JSON/TOML interchange supports those
definitions. Scale, Scala, oscillators, Python bindings and WebAssembly remain
outside this implementation.

The crate also implements [modulation routes, control declarations and binding
value types](rust-modulation.md), including scalar reference evaluation and
explicit reporting of unresolved generator/processor references. Full
instrument/effect preparation and runtime integration remain with consumers.

The [generator-definition module](rust-envelfo.md) adds LFO, Envelope, SampleHold,
Stages, Patch and unresolved reference models, portable JSON/TOML bodies,
configurable preparation limits, graph ranges and captured-approach mathematics.
Envelfo scores, public rate parameters and materialization are implemented, as
are generator-aware binding checks with typed outstanding requirements for
unresolved references, followers and target compatibility. The native score enum
supports Tuning and Envelfo; other score kinds remain unported.

Generator execution belongs to the separate `engelfo` crate. Enge already uses
Rust uFor for LFO, named-Envelope and main voice-amplitude preparation. Further
graph, modulation and tuning adoption is tracked in
[enge's integration plan](https://github.com/rec/enge/blob/main/plan/rust-ufor-integration.md).
Full instrument/effect documents, processing settings, resource resolution and
TempoMap are separate milestones, not prerequisites for the completed APIs.

The crate uses Rust 2024 with a minimum compiler version of 1.85. Import symbols
from their defining modules:

```rust
use ufor::expression::evaluate;
use ufor::number::Rational;

let value = evaluate("5/4")?;
assert_eq!(value.rational(), Some(Rational::new(5, 4)?));
let step = evaluate("2^(1/12)")?;
assert!(step.rational().is_none());
# Ok::<(), ufor::error::Error>(())
```

`Number` distinguishes exact `Rational` values from approximate finite `f64`
values. Rational components are reduced signed 64-bit integers with positive
denominators. Arithmetic cross-cancels where possible, checks overflow, and
returns `Error::ArithmeticRange` rather than silently converting an exact result
to float. Fractional powers produce approximate values even when their numerical
result is an integer. `Rational::from_f64` recovers the exact binary fraction only
when its components fit the same bounds.

The expression parser accepts decimal/scientific literals, parentheses, unary
signs, division, and `^` powers. It implements the documented grammar directly,
including leading zeroes and whitespace between tokens. Limits are 4096
characters, 64 levels of parentheses or syntax depth, and exponent magnitude
1024 for powers. Scientific exponents have a separate magnitude limit of 4096;
exact literal construction and intermediate arithmetic must still fit 64 bits.
Signed and zero expressions are permitted; `Number::positive` supplies the
additional pitch constraint.

`limit_denominator` approximates the exact input, including the binary fraction
of an approximate value. Ties favor the smaller denominator, then the lower
value when the denominators also tie. Numeric display uses Rust's formatting
and is not a canonical cross-language serialization of approximate values.

Validated constructors and Serde deserialization reject the same invalid
definitions. Source fields and evaluated tables are private and immutable;
construct a new value to edit a definition. Methods return typed `Error` values
for domain, arithmetic, positivity, or work-limit failures.

```rust
use ufor::codec::{self, Format};
use ufor::tuning::{Computed, Source, Tuning};

let tuning = Tuning::new(Source::Computed(Computed::default()), 69, "440Hz".into(), 0.0)?;
assert_eq!(tuning.evaluate(81)?.to_string(), "880");
let text = codec::tuning_text(&tuning, Format::Toml)?;
assert_eq!(codec::parse_tuning(&text, Format::Toml)?, tuning);
# Ok::<(), ufor::error::Error>(())
```

`codec::parse_tuning` / `tuning_text` handle tuning bodies;
`codec::parse_score(text, format, limits)` / `score_text` handle the typed
`score::Score` enum with `Tuning` and `Envelfo` variants. Select JSON or TOML
with `Format`. Both operate on supplied UTF-8 strings and preserve expression
spelling except unit normalization. The score codec requires an explicit supported
`kind`; typed `TuningScore` and `EnvelfoScore` deserialization can supply their
respective defaults. `PreparationLimits` configures EnveLFO preparation; tuning's
fixed table/materialization bounds remain unchanged. Direct Serde use
also validates models, while the codec additionally enforces the Python codec's
16,777,216-character, 100,000-value and 64-level document budgets.

Tables may have at most 10,000 entries. The same limit applies to materializing
`Computed::as_ratios()`, while the stored computed note count may be any positive
`i64`. Finite sources reject notes outside their domain. Repeating sources use
Euclidean division for negative degrees. Detuning must produce a positive finite
frequency; underflow, overflow and approximation to zero are explicit errors.

The portable frequency units are `Hz`/`hertz`, `kHz`/`kilohertz`,
`mHz`/`millihertz`, and `MHz`/`megahertz`. Detuning supports
`cent`/`cents`/`musical_cent`, `semitone`, and `octave`/`oct`.
Unit spellings are case-sensitive. A quantity may use one unit factor attached
to a numeric power/sign term or parenthesized expression, or a bare unit meaning one unit.
For example, `1 kHz / 3` and `(440/3) Hz` normalize to exact hertz expressions;
`2^3 kHz` means 8,000 Hz. Use parentheses for powers of an entire quantity.
Division and powers must leave the expected dimension: `1/(3 kHz)` and `1Hz^2`
are rejected. Multiple unit factors and general Pint syntax are outside this
adapter. Unitless frequency strings retain their spelling.

Python installation remains independent of Rust. The core uses Serde,
`serde_json` and `toml` for document interchange and shared conformance cases,
without Python or host-library dependencies.

Run the native checks from the repository root:

```sh
cargo test --workspace --locked
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
```

The release workflow runs these checks on Linux, Windows, and macOS with the
minimum compiler and current stable Rust. A local macOS result does not establish
that those hosted jobs have passed.

Python and Rust pass the same shared definition, expression, preparation, unit
and document cases. Python uses `model_validate` or `model_validate_json` with
`context={'portable': True}` for strict portable input; the score codec applies
that context automatically. Ordinary Python construction retains authoring
coercions and broader Pint syntax. Both languages enforce checked pitch
arithmetic and preparation limits during evaluation. No tuning expected failures
remain. Hosted platform qualification is still tracked in [the plan](../plan/rust-tuning.md).
