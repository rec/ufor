# Tuning contract inventory

The implemented portable contract for [the Rust tuning port](rust-tuning.md).
Python and Rust consume `conformance/tuning.json` and `conformance/pitch.json`.
The Python runner is `test/test_tuning_conformance.py`; Rust integration tests
live in `crates/ufor/tests`. No tuning expected failures remain. Hosted minimum
compiler and three-platform verification remain in the port plan.

## Evidence and fixture format

The shared tuning cases distinguish:

- `valid` and `invalid`: portable definitions and score envelopes.
- `expressions` and `invalid_expressions`: exact/approximate evaluation and rejection.
- `expression_budgets`: padding to a final character count, enclosing parentheses,
  or leading unary plus signs, according to each case's `operation` and `count`.
- `approved_contract`: strict input types, numeric bounds, grammar cases, explicit
  evaluation failures, approved unit aliases and preparation budgets. Both suites
  now enforce these targets as ordinary passing tests.
- `python_characterization`: retained authoring conveniences, including integer
  coercions, broader Pint syntax and construction of nonportable integer fields.
  These cases do not promise that nonportable values can be evaluated or written.

Preparation cases generate a repeated `"1"` table of `count` entries, or
`Computed(notes_per_octave=count, octave_ratio="1").as_ratios()`. Both sides test
admission at 10,000 entries and rejection above it.

Case model names select standalone source classes, `Tuning`, or `TuningScore`.
`normalized` is a complete JSON model dump, including defaults and nulls.
Lookup notes/degrees are decimal strings so readers do not round i64 values
through floating point. Document integer fields remain JSON numbers.

`exact` requires an integer or reduced rational equal to the given rational
string. A numerically matching float is insufficient. `approx` requires a
floating result within the file's absolute/relative tolerances, both `1e-12`.
`outside` requires finite-domain rejection. Evaluation error categories are
`nonpositive-result` and `arithmetic-range`; Python exposes deliberate `ValueError`
failures, while Rust uses typed errors. `as_ratios` checks the complete definition.
Accepted definitions round-trip through JSON; both suites also check tuning TOML.
The fixture version describes its shape, not a new score format version.

## Definitions and validation

| Definition | Defaults | Constraints |
|---|---|---|
| `Computed` | `denominator_limit=0`, `notes_per_octave=12`, `octave_ratio="2"` | Nonnegative limit, positive count and period; computed counts need not materialize |
| `RatioTable` | `repeat_ratio=null`, `name=""`, `description=""` | 1–10,000 positive entries, optional positive repeat ratio; no ordering or unison requirement |
| `IntervalPattern` | `repeat=true` | 1–10,000 positive adjacent intervals |
| `FrequencyTable` | `first_note=0` | 1–10,000 positive hertz expressions and signed i64 starting note |
| `Tuning` | `root_note=69`, `root_frequency="440"`, `detune_cents=0` | Required source, positive anchor even for absolute tables, finite detuning |

A source object uses `ratios`, `intervals`, or `frequencies` to identify a
table or pattern. An empty object or an object containing only computed-source
fields selects `Computed`. Mixed and unknown fields are rejected. Expression
strings retain spelling except for frequency-unit normalization.

`TuningScore` uses `format="recs"`, integer `version=4`, `kind="tuning"`, required
name/title/body, and default empty tags. Header rules come from `score.py` and
`selector.py`. Names are nonempty and trimmed, reject `:#/` and `.*`; titles are
nonempty. Tags require `#` plus a nonempty value without whitespace or `:#/`, and
are deduplicated in order. Typed score validation can default `kind`; the common
score codec requires it to select the score kind.

Python's portable boundary is Pydantic validation with
`context={'portable': True}`, including nested models and JSON validation. The
score codec and migration apply it automatically. It rejects integer/boolean
coercions and integers outside i64. Ordinary Python construction retains authoring
coercions and broader Pint input, but documents must validate as portable values.
Tuning models and the tuning score revalidate existing instances; invalid edited
lists cannot bypass checks when embedded or serialized. Collections remain mutable
in Python, so callers edit the validated model's own collections. Rust constructors
use private immutable fields and require reconstruction for edits.

## Numeric and expression contract

All pitch floating calculations use finite f64 values. Exact numerators are
signed i64; denominators are positive i64. Signs are normalized and fractions
reduced. Cross-cancellation precedes checked products/division. Undefined or
out-of-range literals, intermediates and results fail explicitly. There is no
arbitrary-precision or 128-bit fallback, silent float conversion of exact overflow,
wrapping, clamping or 32-bit variant. Python retains Fraction as its representation,
while the pitch helpers bound the arithmetic before constructing results.

The documented grammar accepts decimal/scientific literals, parentheses, unary
signs, division and `^` powers. Division associates left, powers right, and powers
bind more tightly than a leading sign. Leading zeroes and newlines between tokens
are valid. Limits are 4096 characters, 64 parenthesis/syntax levels, scientific
exponent magnitude 4096 and power magnitude 1024. Numeric construction still has
to fit the 64-bit domain. Negative i64::MIN is a valid signed literal; negating
that exact value again fails. Integer powers remain exact, while fractional
powers are approximate even when the mathematical result is integral.

Denominator approximation uses the exact binary float fraction when its components
fit 64 bits. Continued fractions and distance comparisons use bounded working
values. Ties favor the smaller denominator; equal-denominator half-integer ties
use floor, including negative values. Tests compare Python's bounded algorithm
with Fraction.limit_denominator over small signed rationals and test Rust against
an exhaustive signed search. Approximation to zero is rejected as a pitch result.

## Evaluation and units

Computed lookup is `octave_ratio^(degree/notes_per_octave)` with an optional
maximum denominator. `as_ratios()` independently evaluates every degree and the
repeat ratio; materialization is capped at 10,000 entries.

Repeating tables use floor quotient and nonnegative remainder. Finite ratio
sources accept `[0,N)`, interval patterns `[0,N]`, and frequency tables their
finite contiguous note range. Interval evaluation preserves whole-cycle then
prefix-product order. Relative tunings use checked note subtraction and anchor
multiplication; absolute frequency tables ignore that anchor. Zero detuning
preserves exactness; other detuning multiplies by `2^(cents/1200)`. Nonpositive,
underflowed or nonfinite tuning results fail deliberately.

Portable frequencies support Hz/hertz, kHz/kilohertz, mHz/millihertz and
MHz/megahertz. Detuning supports cent/cents/musical_cent, semitone and octave/oct.
One case-sensitive unit factor can follow a numeric power/sign term or a
parenthesized expression; a bare unit means one unit. `1 kHz / 3`, `(440/3) Hz`
and `2^3 kHz` are covered. Division and powers must retain the expected dimension;
inverse/squared frequency, unit-bearing exponents and multiple unit factors are
rejected. Unitless frequency text retains its spelling. Broader Pint facilities
remain Python authoring conveniences and normalize to canonical portable values.

The Python parser also serves Scala import/export, so those paths now reject
out-of-range exact pitch ratios. Scale naming/intervals, oscillator phase/duty/gain
and general synth cents helpers keep their separate arithmetic, as approved.
Scale.frequency propagates errors from the supplied tuning. These adjacent
Python features are not part of the native Rust coverage claim. Enge is untouched.

## Additional work beyond the prompt

None.
