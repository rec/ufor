# Units

uFor uses reccy's Pint-backed unit parser for authored quantities. Models and
reference calculations retain ordinary numbers, exact fractions, and integer
native timelines. No Pint Quantity objects appear in the public data format.

Bare numbers retain each field's documented canonical unit. Unit strings permit
conversion within the same dimension, for example `250ms` in a seconds field,
`2kHz` in a frequency field, `1 semitone` in a cents field, and `2KiB` in a byte
count. Values must still satisfy the field's range and integer constraints.
Pint parses prefixes, plurals, parentheses, and compound expressions, including
`1 ms / 3`, `1000 millibeats / 3`, and `880 Hz / 2`. A unit alone, such as `ms`,
means one unit. Exact coordinates use rational arithmetic throughout conversion;
expressions that produce an inexact magnitude cannot populate exact-time fields.
Boolean quantities, nonfinite numbers, incompatible dimensions, and fractional
integer counts are rejected.

| Quantity | Canonical unit | Examples |
| --- | --- | --- |
| Physical duration | second | `250ms`, `2 min`, `1/3 s`, `0:00.1` |
| Frequency, sample rate | hertz | `440Hz`, `48kHz` |
| Musical duration | quarter-note beat | `1/3 beat` |
| Tempo | beats per minute | `120bpm`, `2 beat/s` |
| Beat-clock cycle rate | inverse beat | `2/beat` |
| Native position or duration | tick | `48000 tick` |
| Audio sample position or count | frame | `48000 frame` |
| Encoded byte length | byte | `2KiB`, `1MB` |
| Pitch interval | cent or semitone, as declared | `100 cents`, `1 semitone` |
| Logarithmic gain | decibel | `-6dB` |
| Phase | turn | `90degree`, `0.25turn` |
| Modulation angle | radian | `90degree`, `1radian` |
| Modulation voltage | volt | `500mV` |
| Physical light coordinates | meter | `2cm` in a `metres` layout |
| Effect distance | pixel | `2pixel` |
| Effect propagation speed | pixels per second | `12pixel/s` |
| Legacy effect speed per update | pixels per logical frame | `2pixel/frame` |
| Effect decay coefficient | inverse second | `3/s` |

Clock-based LFOs and Motion definitions parse durations and rates in their
selected clock. A beat-clock rate rejects hertz, and a beat duration rejects
seconds. Envelope segments retain their explicit seconds/beat tag and serialize
using `s` or `beat`. Rhythmic steps continue to require an explicit beat unit.

Native tick and frame fields do not implicitly convert seconds. Such a conversion
requires the relevant timebase and belongs to the existing timeline conversion
operations. Large integers remain exact, and `1/3 ms` in a rational seconds field
becomes exactly `1/3000`, without passing through a floating-point value.

Parameter domains, modulation route amounts, and automation values use their
containing declaration's unit. Light positions use their layout's coordinate
unit. Public parameter overrides and presets may contain unit strings; these are
normalized when reference resolution makes the target contract available.
Unresolved references retain those strings rather than guessing a dimension.
Prepared parameters contain canonical numbers.

Clock-relative runtime events and state snapshots without an embedded clock
continue to use canonical rational coordinates supplied by their owning
instrument or host. A standalone coordinate has insufficient information to
convert a physical duration to beats. Unit conversion takes place at the
clock-bearing definition or resolved parameter boundary.

Dimensionless values, ratios, probabilities, MIDI IDs, seeds, enumeration values,
and opaque synth-format integers retain their existing meanings. A lighting
`speed` that multiplies elapsed time is a dimensionless factor. Spatial speeds,
palette cycle rates, and speeds per logical frame retain their distinct units.

Angles, pitch intervals, logarithmic gain, information sizes, musical beats,
frames, and ticks have distinct dimensions in the shared registry. Angles cannot
be normalized controls, and `radian/s` is not cyclic frequency in Hz. `octave`
means 1200 cents. dB remains an authored gain coordinate; amplitude conversion
continues to use the renderer's existing `10 ** (db / 20)`, not Pint's default
power-ratio conversion. Ratio, normalized, and logical ports retain their existing
schema-level compatibility rules.

Patch signals remain dimensionless. Their arithmetic values and thresholds are
numbers, not quantities inferred from a destination parameter. Slew rates are
dimensionless change per second. Adding physical-unit Patch signals is deferred.

Default model and TOML serialization emit canonical values. Seconds, hertz,
frames, and other units remain implied by the field or its declared unit;
Fractions retain their rational representation. Exceptions are explicit-unit
segment durations, rhythmic steps, and unresolved parameter overrides described
above. These are input conveniences, not a new document version.

[Unit conformance examples](../conformance/units.json) give language-neutral exact
conversions and incompatible-dimension cases. The checked-in JSON schemas include
unit-string input alternatives; runtime validation additionally checks dimensions
and numeric constraints.
