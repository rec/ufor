# Rust tuning port

## Goal and boundaries

Introduce a native Rust implementation of uFor's tuning definitions and
mathematics in this repository. Python and Rust should read the same portable
definitions and produce equivalent results. This is the first domain of a
likely full Rust port, not a replacement of the Python package.

The end goal is a uFor library for both Rust and Python that works as closely as
possible the same in both languages. Corresponding features should share domain
concepts, document formats, defaults, validation rules, mathematical behavior,
and failure conditions. Developers moving between languages should be able to
transfer their understanding and data with minimal surprises.

Each language should also offer facilities suited to its developers: Python's
Pydantic models and convenient authoring interfaces, and Rust's enums, ownership,
iterators, and typed `Result` errors. Public APIs should be idiomatic while their
underlying semantics stay aligned. Language-specific conveniences must preserve
the portable contract; unavoidable differences should be documented and tested.
Shared behavior does not require identical syntax, internal representation, or
implementation strategy.

The first milestone ports these five classes from `ufor/tuning.py`:

| Python definition | Rust responsibility |
|---|---|
| `Computed` | Equal divisions, arbitrary positive period ratio, denominator approximation, conversion to a ratio table |
| `RatioTable` | Finite or repeating reference-relative ratios |
| `IntervalPattern` | Finite or repeating adjacent intervals |
| `FrequencyTable` | Absolute frequencies over a finite contiguous note range |
| `Tuning` | Source selection, relative root anchoring, absolute lookup, and detuning |

Port their necessary dependencies from `ufor/expression.py` and
`ufor/number.py`. Include validated JSON/TOML interchange for tuning bodies and
the tuning-only `TuningScore` envelope from `ufor/musical.py`. Reuse the existing
format/version and header rules in `ufor/score.py`; this does not require a Rust
implementation of every score kind or the full library resolver.

Defer `Scale`, accidental naming, Scala import/export, oscillator definitions,
MIDI Tuning Standard encoding, Python bindings, WebAssembly packaging, and
consumer migrations. They can build on the tuning implementation later.
No changes to enge or enge-dependent work are part of this milestone.

## Repository and ownership

Use a root Cargo workspace and one initial crate named `ufor` at `crates/ufor/`, following
the sibling arpeg/enveLFO workspace convention. The crate should contain domain
modules such as `tuning`, `expression`, and `number`, with a small common score
header module when the tuning envelope is added. Callers import public symbols
from their defining modules. Do not make a separate crate for each model.

The root Cargo workspace, lockfile, and initial crate are implemented. Python
sources and packaging remain in their current locations. See
[the Rust implementation guide](../doc/rust.md) for the current coverage and
native verification commands.

The native core must not depend on Python, Pydantic, Pint, NumPy, an audio engine,
devices, filesystem discovery, or network access. Host applications own those
boundaries. Rust must be useful to a native consumer without embedding Python.

Keep the two implementations independent initially. Do not route Python tuning
calls through Rust, require a compiler for Python installation, or introduce an
optional fallback implementation. A later bindings decision should be based on
actual integration needs, separately from this native port.

The portable specification and shared conformance cases are the common contract.
Python is the initial behavioral reference, but an undocumented Python quirk must
be reviewed before becoming a permanent language requirement. Resolve discrepancies
in the specification and fixtures rather than silently changing either language.

## Establish the contract before implementation

The initial [contract inventory and decision register](rust-tuning-contract.md)
is implemented with shared cases in `conformance/tuning.json` and the Python
runner `test/test_tuning_conformance.py`. It separates baseline cases from
Python-specific characterization from approved targets. Strict portable input
types, a finite shared unit syntax, the documented grammar, and safe bounded
evaluation are approved. The initial numeric policy is now uniformly 64-bit:
`f64` floating-point values and checked `i64` mathematical integers and rational
components. Both suites now pass these cases without expected failures. Python
uses `context={'portable': True}` on Pydantic validation, and the score codec
applies that context automatically. Ordinary authoring conveniences remain separate.

Use these existing sources as the starting inventory:

- `doc/musical-format.md`: expression grammar, source domains and tuning semantics.
- `doc/units.md`: authored quantities and canonical units.
- `ufor/tuning.py`, `expression.py`, `number.py`, `base.py`, `score.py`, and the
  tuning envelope in `musical.py`: current implementation and validation rules.
- `conformance/pitch.json` and `conformance/library/scores/tuning.toml`.
- Tuning/expression tests in `test/test_pitch.py`, tuning unit cases in
  `test/test_units.py`, and tuning document cases in `test/test_library.py`.

Extend language-neutral cases to cover every source, defaults, invalid values,
finite boundaries, negative notes, approximation, detuning, normalization, and
document round trips. Both suites must consume the same checked-in data. Expected
results need review; do not generate them by blindly treating current output as
correct. Keep Scala, Scale and oscillator cases outside the first milestone's
coverage claim even though they share `test/test_pitch.py`.

Use strict portable document integers and booleans. Pydantic coercions remain
Python authoring conveniences, not required Rust acceptance behavior. Distinguish
that authoring API from the portable boundary. The portable integer range is
signed 64-bit, even though Python authoring can represent larger integers.

## Numbers and expression evaluation

Use an explicit evaluated-number representation distinguishing exact rationals
from approximate finite `f64` values. An exact integer is a rational with
denominator one. Document strings remain authored strings, rather than exposing
the numeric library's serialization layout as a new wire format.

Python's arbitrary-precision `Fraction` is an implementation fact, not a Rust
requirement. Use `i64` for note indices, counts and rational numerators/denominators,
and `f64` for floating-point values and computations throughout this initial
port. Preserve exact ratios within these bounds, with checked arithmetic and
explicit overflow errors. Positive denominators and nonnegative counts/limits
must fit `i64::MAX`; signed values may reach `i64::MIN`. Reduce/cross-cancel
before checked operations where possible. Do not add arbitrary-precision or
128-bit arithmetic fallbacks, silent conversion of exact overflow to float, or a
parallel 32-bit implementation. A 32-bit variant can be considered if demanded.
Rust's `usize` remains an implementation detail for indexing/allocation, reached
only after checked conversion. Audit sibling calculations without migrating them.

Implement the documented grammar directly with a bounded parser. Preserve:

- Decimal/scientific literals parsed exactly from their text, not through `f64`.
- Left-associative division, right-associative powers, and sign precedence:
  `8/4/2 = 1`, `2^3^2 = 512`, and `-2^2 = -4`.
- Exact division and integer powers; approximate nonintegral powers, matching
  Python's current transition even when the mathematical result is rational.
- Explicit expression and evaluation limits, including syntax depth, signs and
  intermediate operations. Both implementations apply checked 64-bit arithmetic
  to literals, intermediates and reduced results.
- Rejection of unsupported operators, names, calls, division by zero, undefined
  powers, nonfinite results, and out-of-budget expressions.

Keep expression evaluation separate from positive-pitch validation: signed and
zero expressions can be valid expressions while being invalid stored ratios or
frequencies. Approved evaluation rejects nonpositive/nonfinite tuning results and
exposes deliberate arithmetic errors, including approximation-to-zero, underflow,
and overflow. Both implementations enforce these errors.

For approximate results, define explicit per-case absolute/relative tolerances.
Use exact numerator/denominator comparisons for exact cases. Do not require
bit-identical transcendental results across macOS, Windows, and Linux, or allow
a float within tolerance to substitute for an expected exact rational.

## Source semantics and public API

Use a Rust source enum with the existing `kind` values: `computed`, `ratios`,
`intervals`, and `frequencies`. Methods should return `Result` for invalid input,
out-of-domain lookup, or arithmetic failure. Do not use indexing panics, wrapping
integer arithmetic, implicit table wrapping, or silent clamping.

Preserve these details in tests and implementation:

- `Computed`: `notes_per_octave > 0`, nonnegative denominator limit, positive
  `octave_ratio`, and the existing defaults. A nonzero denominator limit uses
  Python `Fraction.limit_denominator` semantics, including tie behavior and the
  exact binary value of an approximate input. Port its algorithm deliberately.
  Test `as_ratios()` separately; approximating each degree is not automatically
  equivalent to approximating one step and repeating it.
- `RatioTable`: nonempty positive entries, optional positive repeat ratio,
  preserved name/description, and no requirement for ascending order or unison.
  For a positive table length, use floor/Euclidean division for negative degrees,
  not Rust's truncation-toward-zero signed `/` and `%`.
- `IntervalPattern`: degree zero is unison. N finite intervals describe N+1
  degrees. Repeating lookup uses the whole-cycle product and the prefix product,
  including negative cycles. Preserve evaluation order for approximate inputs.
- `FrequencyTable`: `first_note` is not necessarily zero; bounds reject both
  ends, and MIDI's 0–127 range is not an implicit limit.
- `Tuning`: relative sources use `note - root_note` and multiply by
  `root_frequency`. Absolute tables ignore that anchor. Detuning multiplies
  either result by `2^(detune_cents/1200)`; zero detuning preserves exactness.

The Rust integer widths are settled at 64 bits. Python's arbitrary-size domain
is not the portable domain. Convert table offsets to
indices only after range checks; apply bounded arithmetic to source evaluation
as well as parsing. Stored ratio, interval and frequency tables are capped at
10,000 entries, and `Computed.as_ratios()` may materialize at most 10,000 entries.
The computed note count itself can still span positive `i64`; lookup does not
materialize it.

Use validated constructors and private invariant-bearing fields in Rust.
Deserialization must go through the same validation. Do not cache evaluated
tables behind publicly mutable vectors. Python currently permits list edits and
revalidates on embedding and serialization; retain that behavior in Python, while defining Rust
edits as construction of a newly validated value. Include edit/reconstruction
cases so stale cached ratios cannot become a cross-language difference.

## Interchange and units

Preserve field names, discriminator values, defaults, optional `repeat_ratio`,
metadata, and expression spelling through JSON and TOML. Serialization equivalence
means equivalent document values, not identical whitespace, field order, or TOML
comments. Unknown fields must be rejected like Python's base model.

Use Serde with validated deserialization and the existing internal `kind` tag;
see [enum representations](https://serde.rs/enum-representations.html) and
[container attributes](https://serde.rs/container-attrs.html). Do not rely on
derive alone to enforce positivity, bounds, finite floats, or defaults. Normal
Rust construction must not bypass those checks either. Add JSON/TOML adapters
without a generic registry for score types that have not yet been ported.

Frequency strings such as `440Hz` and `2kHz` normalize through the same finite
unit adapter at both portable boundaries. Broader Pint facilities remain Python
authoring conveniences. The approved shared syntax supports Hz/hertz, kHz/kilohertz,
mHz/millihertz and MHz/megahertz for frequencies; cent/cents/musical_cent,
semitone and octave/oct for detuning. Numeric pitch expressions may contain one
unit factor, including `1 kHz / 3`. Broader Pint syntax remains a Python authoring
facility. Rust evaluation itself consumes canonical quantities.

Read/write adapters operate on supplied text or bytes with an explicit UTF-8
contract, not paths, locale-dependent numbers, or platform-native separators.
The tuning envelope must preserve `format = "recs"`, integer `version = 4`,
required names/titles, tags, and validation. Do not bump the format merely to
introduce another implementation.

## Implementation sequence

The native implementation in `crates/ufor` covers all five tuning definitions,
the tuning score envelope, bounded numbers/expressions, the approved units,
and JSON/TOML interchange. Rust 2024 / Rust 1.85 is the declared baseline.
Rust tests consume baseline definitions, approved rejection cases, shared
expression and preparation budgets, and the existing Python tuning TOML fixture.
Both formats round-trip through validated deserialization. Numeric tests cover
cross-cancellation, signed bounds, binary floats, and exhaustive small denominator
approximations. See [the implementation guide](../doc/rust.md).
Local verification currently uses macOS and the installed compiler; minimum
compiler and other platform results remain unverified until release CI runs.

Python alignment is implemented in `ufor/expression.py`, `number.py`, `tuning.py`,
and the existing score codec. The effects on adjacent domains were reviewed:
Scala uses the checked parser; Scale naming/intervals, oscillator controls and
general synth cents calculations retain their existing arithmetic. The shared
cases and focused regressions cover this boundary. See
[portable Python validation](../doc/validation.md#portable-python-tuning-input).

Remaining work:

1. Obtain native minimum-compiler and three-platform evidence from the configured
   release workflow. The Rust jobs already cover Rust 1.85 and stable on macOS,
   Windows and Linux; do not claim those results from local macOS checks.

## Verification and completion

Rust integration tests read the same conformance files as Python; they must not
need Python at runtime. Add a tracked differential test harness only where fixed
fixtures cannot adequately cover the number/parser contract. All generator seeds,
procedures, and expected-value rules must be reproducible from committed sources.
Keep development tooling in the repository, never solely in temporary directories.

Run `cargo test --workspace --locked`, formatting checks, and Clippy across all
targets/features actually introduced. Run the applicable Python suite, Ruff,
formatting, type checking and pyupgrade whenever Python or shared test data changes.
Exact cases, rejection cases, and interchange results must agree; approximate
cases must meet their explicit tolerances.

The existing release workflow builds and tests Rust and the non-editable Python
package on macOS, Windows, and Linux. It tests the declared minimum
Rust version and a current stable toolchain. Do not trigger workflows on every
commit. Native local results do not establish hosted results for other systems.
WebAssembly and additional architectures remain later qualification work.

The milestone is complete when all five tuning definitions, their required
mathematics, and tuning-only JSON/TOML documents conform in both languages;
unit and integer boundaries are documented; no consumer migration or Python
compiler requirement was introduced; and the three-platform checks provide
native evidence. Do not describe Scale, Scala, the full score codec, or all uFor
features as ported on the strength of this milestone.

## Growing toward the full port

Keep shared numeric and document-header behavior in reusable domain modules;
future ports add modules to the same crate before considering crate splits.
Scala conversion, Scale and accidental naming now have native implementations
and shared conformance cases in `conformance/scala.json` and
`conformance/scale.json`. Grow serialization coverage alongside each domain.

Each later feature needs one documented portable contract and conformance cases
exercised by both implementations. A wire-format change affects both languages;
an implementation-specific optimization must preserve those cases. Publish an
implemented-feature matrix as coverage grows. Decide bindings, consumer adoption,
packaging and release-version coordination when they become actual work, without
assuming that Python will permanently duplicate every Rust internal detail.

## Additional work beyond the prompt

None.
