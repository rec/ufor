# Tuning contract inventory

Characterization for the first stage of [the Rust port](rust-tuning.md), checked
against the Python implementation and locked dependencies on 2026-11-15. This
records current behavior alongside the approved directions, including a uniform
64-bit numeric policy for the initial port. The native Rust implementation now
conforms to the baseline and approved cases; Python production behavior remains
unchanged. See [current coverage and APIs](../doc/rust.md).

## Evidence and fixture format

`conformance/tuning.json` supplements `conformance/pitch.json`. The Python runner
is `test/test_tuning_conformance.py`; existing pitch, unit, editing and document
tests remain relevant. The new data separates:

- `valid` and `invalid`: baseline definition and envelope cases.
- `expressions` and `invalid_expressions`: mathematical evaluation and rejection.
- `expression_budgets`: boundary inputs built by the specified operation. `count`
  is the final padded length, number of enclosing parentheses, or number of
  leading plus signs, respectively. These operations require no Python syntax
  knowledge in a Rust runner.
- `python_characterization`: current Python behavior, including differences from
  approved directions. These do not require Rust to copy it.
  Construction cases name their decision; the expression cases concern the
  parser/number decision. Do not promote them to shared requirements implicitly.
- `approved_contract`: target cases for strict portable input types, documented
  expression syntax, numeric bounds and explicit evaluation failures. The runner marks
  known Python alignment gaps as strict expected failures: an unexpected pass
  requires updating their status, and unrelated exception types still fail.
  Error categories describe intended Rust errors; Python alignment must at least
  expose a deliberate `ValueError` rather than raw arithmetic exceptions.
  Target tests currently exercise the existing model entrypoints. When a portable
  document validation boundary is implemented, direct those tests to that boundary
  rather than requiring authoring constructors to lose their conveniences.
  Its `preparation_budgets` generate a repeated `"1"` table of `count` entries,
  or `Computed(notes_per_octave=count, octave_ratio="1").as_ratios()`.
  Boundary admission is shared; over-limit rejection remains an expected Python
  failure. Unit alias lists and `maximum_table_entries` record the approved
  portable subset and preparation cap.

Case model names select standalone source classes, `Tuning`, or `TuningScore`.
Inputs are ordinary document objects; `normalized` is the complete expected
JSON model dump, including defaults and null fields. Lookups use decimal **strings**
for note/degree arguments so a fixture reader cannot accidentally round a large
integer through a JSON float. Document integer fields remain JSON numbers.

`exact` is a rational string accepted by `Fraction`, including decimal/scientific
notation. Exact results must be rational/integer, never approximate floats.
`approx` requires a floating result within the fixture's explicit absolute and
relative tolerances, currently both `1e-12`. `outside` means finite-domain
rejection. A characterization lookup's `raises` names the observed Python
exception; it does not prescribe the future Rust error type. `as_ratios` checks
the entire resulting ratio definition, including its serialized values.

An approximate expected zero requires floating zero exactly, with no absolute
tolerance that could conceal a small nonzero value in an underflow case.

Every accepted definition is tested through JSON serialization/deserialization;
tuning-envelope cases also pass through the common TOML codec. Fixture `version`
identifies this test-data shape, not a new uFor document version. Expected values
are explicit, not regenerated from Python outputs. For example, the negative
ratio cases follow floor division, `440/3 * 5/4 = 550/3`, and octave detuning
doubles frequency. Approximation ties are recorded explicitly.

## Definitions, defaults and validation

All five definitions inherit frozen model attributes, unknown-field rejection,
finite float validation, and validated defaults from `ufor/base.py`.
Lists remain mutable in Python despite frozen attributes. Numeric expression
strings are retained verbatim except frequency-unit normalization described below.

| Definition | Fields and defaults | Construction constraints |
|---|---|---|
| `Computed` | `kind="computed"`, `denominator_limit=0`, `notes_per_octave=12`, `octave_ratio="2"` | Limit nonnegative; note count positive; period evaluates positive |
| `RatioTable` | `kind="ratios"`, required `values`, `repeat_ratio=null`, `name=""`, `description=""` | Nonempty list of positive expression strings; repeat ratio positive when present; no ordering or unison requirement |
| `IntervalPattern` | `kind="intervals"`, required `intervals`, `repeat=true` | Nonempty list of positive expression strings |
| `FrequencyTable` | `kind="frequencies"`, required `values`, `first_note=0` | Nonempty positive frequency-expression strings; unrestricted signed integer starting note |
| `Tuning` | Required `source`, `root_note=69`, `root_frequency="440"`, `detune_cents=0` | Source dict needs a known `kind`; root frequency positive even when absolute source ignores it; detune finite |

Standalone source construction can omit its own `kind` and use the class default;
a source dictionary inside `Tuning` cannot omit the union discriminator.
Neither ratios nor intervals have a frequency dimension. Bare numeric values in
their string fields are rejected; expression strings must be supplied.

The tuning score class requires `name`, `title`, and `body`, and defaults to
`kind="tuning"`, `format="recs"`, integer `version=4`, and empty tags. The common
score codec needs `kind` in input to select that class. Names use the
current score-name restrictions, titles are nonempty, and tags are validated and
deduplicated in order. Boolean and floating versions are rejected. These common
header rules come from `score.py` and `selector.py`, not new Rust-only conventions.

## Evaluation and exactness

`Computed(d)` evaluates `octave_ratio^(d/notes_per_octave)`. Integral rational
exponents preserve rational results; fractional exponents produce floats, even
for `9^(1/2) = 3`. With a nonzero limit, the result is passed to
`Fraction(result).limit_denominator(limit)`. Approximate inputs therefore use the
exact binary float as the approximation target, not its rounded display string.
`3/2` with maximum denominator one chooses one; `5/2` chooses two.
`as_ratios()` computes each degree independently and stores their string forms.

Repeating tables split degree into floor quotient and nonnegative remainder.
Finite ratio tables accept `[0,N)`, finite interval patterns accept `[0,N]`,
and finite frequency tables accept `[first_note, first_note+N)`. Repetition is
never inferred from a frequency table. A finite interval pattern's zero-degree
empty product is integer one; other exact products commonly return `Fraction`.
This Python representation difference does not justify different Rust semantics.

`Tuning` multiplies relative sources by the anchor frequency and uses relative
note offsets. Absolute sources use their own note index without that anchor.
Zero detuning preserves exact results; nonzero detuning produces floats through
`exp2(detune_cents/1200)`. Tables reevaluate their current list contents on each
call. The existing codec revalidates edited definitions before TOML serialization.

## Expressions and resource limits

The portable grammar and precedence are documented in `doc/musical-format.md`.
Existing `pitch.json` covers division associativity, powers and sign precedence.
The new cases add exact scientific notation, zero/negative values, integral
results of fractional powers, and intermediate values larger than the final result.

The current parser uses Python's AST after translating `^` to `**`. This leaks
Python lexical rules: `01` and a bare newline before `/` are rejected, whereas
the same newline inside parentheses is accepted. Ordinary token whitespace is
broader in the written grammar. The approved target follows that grammar: `01`
means one, and a newline between tokens is whitespace. Python parser alignment
is still required; the old outcomes remain characterization evidence.

Expression limits are 4096 input characters, 64 parenthesis levels and AST depth,
scientific exponent magnitude 4096, power magnitude 1024, and 16384-bit exact
numerators/denominators. Parenthesis and AST limits are separate: parentheses do
not create AST nodes. Power admission conservatively estimates growth from the
base's bit length before exponentiation, so it can reject a result that would
fit after evaluation. The scientific-exponent bound is not a promise that every
number below it is accepted.

The final `math.isfinite` converts exact values to float: `2^1024` and `1e309`
are rejected even though their exact integers fit the bit budget. Intermediate
`2^1024/2^1024` succeeds with exact result one. Tiny exact `1e-400` remains a
positive rational, while its fractional power may underflow to floating zero.
In `1e-400^(1/2)`, conversion of the base to float loses the value before the
power is applied, even though the mathematical result `1e-200` is representable.

Those expression budgets are not uniformly enforced by source evaluation:
`Computed.__call__` raises a `Fraction` to its degree outside the bounded parser,
and table repetition/product calculations also happen outside it. Large note
arguments can therefore exceed expression arithmetic budgets. Large approximate
degrees and detuning can raise raw `OverflowError`; negative detuning can
underflow to zero. A positive ratio `1/4` approximated with maximum denominator
one becomes exact zero. Do not silently change these behaviors in this stage.

## Authored input and unit normalization

Pydantic currently accepts booleans, integral floats, and numeric strings in
ordinary integer fields. It rejects fractional floats there. `repeat` also
accepts values such as the string `"false"`. In contrast, version validation
rejects booleans/floats, and reccy's detuning unit validator rejects booleans.
These differences should be resolved intentionally, not inherited accidentally
by a Rust deserializer.

Frequency values and the anchor are required strings. Unit-bearing strings
normalize to exact hertz-expression strings, e.g. `2kHz -> "2000"`,
`440 hertz -> "440"`, and `1 kHz / 3 -> "1000/3"`. Unitless expressions retain
their spelling. Detuning normalizes `1 octave -> 1200.0` and
`1 semitone -> 100.0`; incompatible dimensions are rejected.

The authoritative dependency is the reccy revision in `uv.lock`, with its Pint
registry. These examples are a tested minimum, not an exhaustive grammar for all
Pint aliases, prefixes and arithmetic. A general-purpose units library port is
not implied. More spellings can be characterized once the portable unit boundary
is chosen; changing locked dependencies can change characterization results.

## Approved directions

The user approved the four initial recommendations and subsequently chose
64-bit numbers throughout, with any 32-bit version deferred until demanded.

| Decision | Approved direction | Implementation status |
|---|---|---|
| Portable input types | Strict JSON integers and booleans at the portable document boundary; broader Python authoring conveniences may remain separately documented | Add portable validation without silently removing Python authoring conveniences |
| Units boundary | A finite shared tuning-specific syntax; additional Pint facilities can remain Python-specific | Implemented in Rust and covered by shared alias cases; see the exact syntax below |
| Parser and numeric boundaries | Follow the documented grammar; use `f64` and checked `i64` values, including rational components | Align Python's portable boundary rather than copying its 16384-bit arithmetic or float-conversion artifacts |
| Evaluation safety and positivity | Bound work and reject nonpositive/nonfinite tuning results with explicit arithmetic failures | Apply the agreed limits to source evaluation and materialization too; do not clamp, wrap, or silently lose exactness |

The approved aliases are Hz/hertz, kHz/kilohertz, mHz/millihertz and
MHz/megahertz for frequency; cent/cents/musical_cent, semitone and octave/oct for
detuning. Numeric pitch grammar admits one unit factor following a numeric power/sign term,
including `1 kHz / 3` and `(440/3) Hz`; a bare unit means one unit. Division and
powers must retain the expected dimension. Rust rejects inverse frequency,
squared frequency, unit-bearing exponents and multiple unit factors. Broader
Pint syntax remains Python-only authoring. The exact aliases are exercised by
both suites. Stored tables and computed-table materialization are capped at
10,000 entries in Rust, with Python alignment still pending.

### Numeric policy: 64-bit throughout

Unlimited precision is not a requirement. The original recommendation privileged
Python compatibility too strongly. Distinguish three separate questions:

- Note indices and counts need practical integer ranges, not arbitrary precision
  merely because Python permits it.
- Exact ratios need numerator/denominator capacity to retain musical
  relationships, not an unlimited frequency range. `(81/80)^100` is about 3.46,
  but its reduced numerator and denominator each have roughly 190 decimal digits.
  A small final value does not imply small exact components.
- Floating-point magnitude is separate from exact precision. `f64` can represent
  approximately `1e-200` without arbitrary-precision integers. Such extremes can
  be boundary tests without being supported tuning requirements. See the
  [Rust f64 reference](https://doc.rust-lang.org/std/primitive.f64.html).

Use `f64` for every floating-point value and computation in the initial port.
Use checked `i64` for note indices, counts, limits, and exact rational components.
Signed integer bounds are -9223372036854775808 through 9223372036854775807;
counts/limits remain nonnegative, note counts remain positive, and denominators
are positive and no greater than 9223372036854775807. Reject inputs outside those
ranges. JSON integer parsing must not first round them through `f64`.

Normalize signs, reduce fractions and cross-cancel before checked operations
where possible. Reject arithmetic that still exceeds 64 bits, including an
intermediate that would overflow before a later division reduces the result.
The signed minimum literal must be accepted as a signed value, without requiring
an out-of-range positive intermediate. Do not add arbitrary-precision or 128-bit
fallbacks, wrapping/saturating arithmetic, or silent conversion of exact overflow
to float. Use `usize` only for indexing/allocation after checked conversion.

The stored components and all arithmetic must respect this policy. Denominator
approximation must not materialize an arbitrarily large binary-float fraction:
implement it with bounded working values and explicit errors when unsupported.
Rust implements the bounded approximation algorithm with checked convergents
and distance comparisons that avoid overflowing cross-products. Tests cover
ties, exact binary float inputs and exhaustive small rational approximations.
Python portable alignment remains work; arithmetic must not widen implicitly.

No 32-bit variant is part of this port; consider one only if demand emerges.
This numeric policy should guide subsequent domains too. Existing protocol-defined
byte fields are not being redesigned, and no current Python representation is
changed by this planning update.

This trades arbitrary exact expression complexity for predictable storage and
arithmetic cost. It would reject some currently accepted exact calculations even
at ordinary musical magnitudes, so it needs explicit overflow cases. Measure
representative tunings before claiming a performance benefit; preparation is not
automatically a per-sample audio cost. The beyond-i64 and extreme exact-expression
cases characterize Python, not a commitment to preserve their domains in Rust.
Use this fixed-width policy when choosing dependencies and the Rust API.

Retain the initial `1e-12` comparison tolerances for approximate `f64` results;
they are not a promise of bitwise identity across platforms. Review tolerances
against the native conformance results before claiming equivalence.

Keep current observations and approved targets distinguishable until Python
alignment is implemented. Then remove the expected-failure markers and update
the specification in the same change. Do not require Rust to reproduce Python
quirks merely to satisfy characterization cases.

## Additional work beyond the prompt

None.
