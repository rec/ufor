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

Each score has one named physical timebase with an exact rational rate. Curve
ticks are strict signed integers in that timebase. A curve names its unit and
contains strictly increasing knots. It has at least one knot; a score can have
no curves, in which case it evaluates to its base value.

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

The caller must provide at most one automation score for a target in a resolved
scope. Resolving competing scores, manual controls, and generator routes together
belongs to future graph preparation. Existing instrument modulation and audio
arrangement automation keep their current contracts; this score adds the missing
typed scalar timeline representation.

## Verification and boundaries

[conformance/automation.json](../conformance/automation.json) contains portable
queries and expected values for the three TOML examples. Tests also cover editing
and serialization, invalid units and domains, competing writers, explicit
combination, and large timestamps.

The score participates in the common codec and generated
[schema/scores.json](../schema/scores.json). No GUI, audio renderer, device
adapter, dense-array format, general graph integration, or equal-power/logarithmic
mapping is introduced by this first scalar profile.
