# Rust tuning port

## Goal and boundaries

Introduce a native Rust implementation of uFor's tuning definitions and
mathematics in this repository. Python and Rust should read the same portable
definitions and produce equivalent results. This is the first domain of a
likely full Rust port, not a replacement of the Python package.

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

Use a root Cargo workspace and one initial crate at `crates/ufor-core/`, following
the sibling arpeg/enveLFO workspace convention. The crate should contain domain
modules such as `tuning`, `expression`, and `number`, with a small common score
header module when the tuning envelope is added. Callers import public symbols
from their defining modules. Do not make a separate crate for each model.

Keep Python sources and packaging in their current locations. Add `Cargo.toml`,
`Cargo.lock`, crate sources, Rust integration tests, and any necessary CI changes
only when implementation begins. This planning change adds none of them.

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

Record the accepted document input types explicitly. Pydantic sometimes coerces
values that Serde would reject, including integral floats or booleans in integer
fields. Characterize those cases and agree on the portable input contract before
implementing coercion. Do not impose a stricter Rust schema or silently narrow
Python integers to a machine-sized type and call that parity.

## Numbers and expression evaluation

Use an explicit evaluated-number representation distinguishing exact rationals
from approximate finite `f64` values. An exact integer is a rational with
denominator one. Document strings remain authored strings, rather than exposing
the numeric library's serialization layout as a new wire format.

Python's `Fraction` has arbitrary-precision integers. Use an arbitrary-precision
rational implementation in Rust, with the existing expression bounds, rather
than `Ratio<i64>` or `f64` for everything. Candidate dependencies are
`num-bigint`, `num-rational`, and the traits needed for checked conversions;
choose their versions and features during implementation. The
[num-rational documentation](https://docs.rs/num-rational/latest/num_rational/type.BigRational.html)
defines `BigRational` as `Ratio<BigInt>`. Audit existing sibling Rust tuning
calculations for later reuse opportunities, but do not migrate them here.

Implement the documented grammar directly with a bounded parser. Preserve:

- Decimal/scientific literals parsed exactly from their text, not through `f64`.
- Left-associative division, right-associative powers, and sign precedence:
  `8/4/2 = 1`, `2^3^2 = 512`, and `-2^2 = -4`.
- Exact division and integer powers; approximate nonintegral powers, matching
  Python's current transition even when the mathematical result is rational.
- The existing 4096-character, 64-level, scientific-exponent 4096, power 1024,
  and numerator/denominator 16384-bit limits. Define matching boundary cases
  for syntax depth, signs, and intermediate operations in both implementations.
- Rejection of unsupported operators, names, calls, division by zero, undefined
  powers, nonfinite results, and out-of-budget expressions.

Keep expression evaluation separate from positive-pitch validation: signed and
zero expressions can be valid expressions while being invalid stored ratios or
frequencies. Preserve the existing behavior at the point of failure, including
float-conversion overflow and underflow; review discrepancies explicitly.

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

Python accepts arbitrary-size note integers. Choose an exact Rust argument type
or document and approve a bounded contract before implementation; do not assume
`usize`, `i32`, or `i64` defines the portable domain. Convert table offsets to
indices only after range checks. Evaluation budgets outside the expression
parser also need explicit decisions if huge note values expose unbounded work;
new limits must not be slipped into a typing or parser change.

Use validated constructors and private invariant-bearing fields in Rust.
Deserialization must go through the same validation. Do not cache evaluated
tables behind publicly mutable vectors. Python currently permits list edits and
revalidates on serialization; retain that behavior in Python, while defining Rust
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

Frequency strings such as `440Hz` and `2kHz` currently normalize through reccy's
Pint-backed parser; detuning accepts musical-cent quantities. This is a real input
contract, not an optional display feature. First enumerate the tuning-specific
spellings and expressions accepted by Python and represent their normalized
results as shared cases. Decide and document the portable Rust unit syntax before
implementing that boundary. Do not claim complete authored-input parity if Rust
only handles canonical numeric expressions. A general Pint replacement is outside
this milestone; any proposed restriction of Python's accepted syntax requires a
separate decision. Rust evaluation itself consumes canonical quantities.

Read/write adapters operate on supplied text or bytes with an explicit UTF-8
contract, not paths, locale-dependent numbers, or platform-native separators.
The tuning envelope must preserve `format = "recs"`, integer `version = 4`,
required names/titles, tags, and validation. Do not bump the format merely to
introduce another implementation.

## Implementation sequence

1. Complete the input/number/unit contract inventory and expand shared fixtures.
   Resolve integer-domain and unit-syntax decisions before committing to a public
   Rust API. Leave existing Python behavior unchanged during characterization.
2. Add the workspace and initial crate. Set and test an explicit Rust minimum
   version, considering the siblings' edition 2024 / Rust 1.85 baseline and the
   selected dependencies. Commit the lockfile. Keep Python installation independent.
3. Implement bounded exact-number and expression evaluation, with negative and
   approximate cases, before exposing tuning constructors.
4. Implement the four source types and `Tuning`, then denominator approximation
   and `as_ratios()`. Validate direct construction and deserialization equally.
5. Add JSON/TOML and tuning-envelope interchange, including agreed unit
   normalization. Test Python-to-Rust and Rust-to-Python round trips through
   tracked fixtures or tracked test tooling, without native Python bindings.
6. Complete platform checks and documentation. Replace completed plan entries
   with links to the implementation and its public usage examples.

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

Extend the existing release workflow for macOS, Windows, and Linux to build and
test Rust as well as the non-editable Python package. Test the declared minimum
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
Scale/accidentals and Scala conversion are natural next milestones, followed by
other domains according to consumer needs. Grow serialization coverage alongside
each domain rather than adding opaque placeholders for every unported score.

Each later feature needs one documented portable contract and conformance cases
exercised by both implementations. A wire-format change affects both languages;
an implementation-specific optimization must preserve those cases. Publish an
implemented-feature matrix as coverage grows. Decide bindings, consumer adoption,
packaging and release-version coordination when they become actual work, without
assuming that Python will permanently duplicate every Rust internal detail.

## Additional work beyond the prompt

None.
