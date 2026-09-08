# Musical definitions

Ufor owns pitch and scale semantics and oscillator parameters. Tuney owns its
editable configuration, Scala collection browser, units/UI annotations, broader
expression authoring, and existing NumPy audio implementation. Ufor has no
NumPy, Reccy, device, GUI, or plugin dependency.

## Pitch expressions

Frequency and ratio values are strings, preserving human notation such as
`5/4`, `2/3`, `440/3`, and `2^(1/12)` through JSON and TOML round trips.
The portable grammar is:

```text
expression = division
 division  = signed { "/" signed }
 signed    = ( "+" | "-" ) signed | power
 power     = atom [ "^" signed ]
 atom      = number | "(" expression ")"
```

Numbers are decimal integers, decimals, or scientific notation. Whitespace is
allowed between tokens. Division associates left; exponentiation associates
right and binds more tightly than a leading sign. Thus `8/4/2 = 1`,
`2^3^2 = 512`, and `-2^2 = -4`. Integer powers and division preserve rational
values; nonintegral powers may require floating-point evaluation. Stored pitch
values must evaluate to positive finite real numbers. No function calls,
names, addition, multiplication, modulo, or Python `**` operator are accepted.
Tuney's broader authoring evaluator compiles its results into portable values.

This grammar makes the user's stated `/` and `^` operators concrete. A separate
original grammar implementation was not located during extraction; additional
syntax must be reconciled explicitly, not inferred from Tuney's Python AST
language. In Ufor expressions `100.0` means one hundred. Only the Scala importer
interprets a decimal-point pitch entry as cents.

## Tuning sources

| Source kind | Meaning | Domain |
| --- | --- | --- |
| `frequencies` | `values` are absolute Hz, starting at `first_note` | Finite; both ends reject out-of-range access |
| `ratios` | `values` are ratios relative to the reference pitch | Finite unless `repeat_ratio` is specified |
| `intervals` | Each entry is an adjacent frequency ratio | Finite or repeating, controlled by `repeat` |
| `computed` | Equal divisions of `octave_ratio` | All integer degrees |

For repeating reference ratios, with N values, write degree = qN + r using
floor division and 0 <= r < N. The ratio is `repeat_ratio^q * values[r]`.
The entries include the reference degree; the repeat multiplier is separate.
There is no requirement for ratios to ascend.

For adjacent intervals, degree zero is unison. Degree d accumulates the first
d intervals. A repeating pattern's multiplier is the product of its entries.
One `2^(1/12)` interval represents twelve-tone equal temperament with a step
period of one; twelve steps multiply frequency by two. A finite list of N
intervals describes N+1 degrees. Negative degrees require repetition.

`Tuning.root_note` anchors relative degrees; `root_frequency` is Hz and may be a
fractional expression. `detune` is cents, multiplying by `2^(detune/1200)`.
Absolute frequency tables use their own note indexes and ignore the root
anchor; detune still applies. Instrument range wrapping is host policy and is
never a property of the portable frequency table.

`Computed.limit` is a maximum rational denominator, matching Tuney's actual
`Fraction.limit_denominator` behavior. It is not a prime-limit JI selector.

## Scales and interchange

`Scale` preserves Tuney's alphabet, root/begin/end, interval selection, note
filter, accidentals, and offset. Its intervals are counts of tuning degrees,
not frequency ratios. Naming a note and determining its frequency are separate
operations. The shared implementation covers negative notes and half accidentals.

Scala imports insert degree-zero unison, retain integer ratios, convert cents
to `2^(cents/1200)`, and put the final Scala pitch in `repeat_ratio`. Export
requires a repeating table beginning at unison. Fractions remain fractions;
non-rational powers are written as cents with twelve decimal places. Text
encoding and file access belong to the host. Scala keyboard mapping (.kbm)
is not implemented in this extraction.

MTS per-key mappings correspond to finite frequency tables, usually indexed
0..127. No implicit period is inferred. MTS no-change sentinels are protocol
operations, not zero-Hz pitches; a host applies updates before constructing the
resolved table. Tuney retains its existing MIDI byte encoding and delivery.
Ufor does not yet provide an MTS byte decoder or sparse update document.

## Oscillator contract

`Oscillator` carries `waveform` (sine, square, triangle), `duty_cycle` in [0,1],
`key_scale_note`, and `key_scale` in dB per twelve note steps. Gain is
`10^(key_scale*(note-key_scale_note)/240)`. The twelve-step gain unit is an
existing Tuney convention, independent of tuning period.

For phase p in [0,1), the existing Tuney realization uses:

- sine: sin(2*pi*p), independent of duty cycle;
- square: +1 when p < duty, otherwise -1;
- triangle: 2*p/duty-1 when p < duty, otherwise
  (1+duty-2*p)/(1-duty). At duty=0 only the falling branch applies; at duty=1
  only the rising branch applies. Duty=0.5 is a symmetric triangle.

Tuney samples positions start through start+length, excluding the endpoint,
with phase position/period. Its implementation is not band-limited. These are
recorded existing equations, not a mandate to freeze this implementation for
future engines. Ufor contains no waveform buffer generation, phase accumulator,
sampler engine, or new audio renderer. Tuney's existing implementation remains
in Tuney. Envelopes, LFOs, phase/retrigger state, and the final instrument contract
remain the next model-design gate before further audio generation.

## Portable documents and conformance

The common codec accepts `tuning`, `scale`, and `oscillator` document kinds in
addition to recording, sequence, and arrangement. Each has a `body` containing
its definition. The initial extraction deliberately retains `format = "recs"`
and `version = 1`; renaming the wire marker is a later explicit migration.

`schema/documents.json` is generated by `ufor.codec.document_schema`.
`conformance/pitch.json` supplies exact rational and approximate numeric cases
for implementations in other languages. The Python tests consume those cases.
Definitions alone do not guarantee audio identity between implementations.
