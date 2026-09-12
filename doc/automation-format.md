# Scalar timeline automation

An automation score edits one resolved parameter over time. This first profile
supports linear gain, frequency, and logical gates. It is data and a pure scalar
evaluator; it neither opens a device nor generates audio.

## Authoring

Start with the editable examples in
[examples/automation](../examples/automation): gain, frequency, and gate.
Use the common codec to load and save them:

```python
from pathlib import Path

from ufor.automation import AutomationScore, evaluate
from ufor.codec import parse_score, score_toml

score = parse_score(Path('examples/automation/frequency.toml').read_text())
assert isinstance(score, AutomationScore)
assert evaluate(score, 2000) == 660.0
edited = score.model_dump()
edited['body']['curves'][0]['knots'][1]['value'] = 1760.0
updated = AutomationScore.model_validate(edited)
Path('edited-sweep.toml').write_text(score_toml(updated))
```

Validate the edited data before saving. Pydantic model_copy(update=...) alone
does not validate edits. The common codec validates again when serializing.

## Quantity and timing contract

| Quantity | Unit | Values | Interpolation |
| --- | --- | --- | --- |
| gain | ratio | Finite, nonnegative numbers; 1 is unity | linear or hold |
| frequency | hz | Finite, strictly positive numbers | linear or hold |
| gate | logical | Booleans, not numbers or voltages | hold only |

The body supplies target (name and parameter), scope, quantity, unit, default,
and curves. Scope uses the existing instrument, part, or voice vocabulary.
A host evaluates a separate resolved context for each scope; this profile does
not infer voice identity or resolve a target against a graph.

Each score has one named physical timebase with an exact rational rate and one
`control` output. The output declares the curve's quantity, unit, scope, and
timebase, and must exactly match the body. Curve ticks are strict signed integers
in that timebase. A curve names its unit and contains strictly increasing knots.
It has at least one knot; a score can have no curves, in which case it evaluates
to its base value.

The unit is explicit and checked against the quantity. No conversion happens
because two values happen to have the same numeric representation. Frequency
interpolation is linear in Hz, not logarithmic pitch. A logical gate is not a
physical CV output. Audio array descriptors and electrical profiles are outside
this milestone.

## Defaults and boundaries

Before the first direct-curve knot, use the instance override, or the declared
default if there is no override. The first knot takes effect at its exact tick.
After the last knot, hold its value. Hold interpolation changes exactly at each
knot; linear interpolation uses the two adjacent values.

A host may limit the score to a clip interval. This profile does not add clip
activation, transport, or conversion between clocks. Query ticks must already
be in the score's timebase. Integer subtraction precedes interpolation, so
large absolute timestamps do not erase short intervals.

## Competing writers

A curve with no operation is a direct writer. At most one is allowed per score,
even if curves would begin at different times: curves hold their final values
and have no implicit end. Explicitly edit them into one curve when sequential
direct automation is intended.

Additional curves must name an operation from the existing modulation model:

- add: contribution in the parameter's unit.
- multiply: dimensionless contribution in ratio units.

The evaluation order matches Ufor modulation:

```text
result = (direct-or-base + sum(additions)) * product(multipliers)
```

Before a contribution's first knot it has no effect. Contributions may be signed,
but the final value must satisfy the target quantity's domain. A negative gain,
zero or negative frequency, or nonfinite result is an error, never an implicit
clamp. Gate automation permits one direct hold curve and no arithmetic writers.

For example, a 660 Hz direct value with an additive -10 Hz offset and a ratio
multiplier of 2 evaluates to 1300 Hz, independently of curve list order.

An arrangement places a reusable automation output through a `control_clips`
entry. Its source interval is in the automation timebase and its timeline start
is in the arrangement timebase. Speed is fixed at one. The body target names a
sibling part and its public parameter; target resolution, rate conversion, and
parameter-domain validation occur when the arrangement is resolved. A rendered
window requests the curve from the clip start through the needed endpoint, so the
host can reconstruct its value at the render start.

The current arrangement profile accepts one part-scoped numeric automation score
per target. Competing writers, logical gates, and voice- or instrument-scoped
automation are rejected rather than given ambiguous behavior. Combining manual
controls, generators, and multiple control writers belongs to later graph
preparation.

## Verification and boundaries

[conformance/automation.json](../conformance/automation.json) contains portable
queries and expected values for the three TOML examples. Tests also cover editing
and serialization, invalid units and domains, competing writers, explicit
combination, and large timestamps.

[conformance/control-clips.json](../conformance/control-clips.json) gives an
exact source/timeline interval conversion vector for a 1 kHz control score in a
48 kHz arrangement.

The score participates in the common codec and generated
[schema/scores.json](../schema/scores.json). Arrangements resolve it without
rendering audio or sending device output. No GUI, audio renderer, device adapter,
dense-array format, general control combiner, or equal-power/logarithmic mapping
is introduced by this profile.
