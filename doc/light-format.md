# Light animations, layouts and wiring

Ufor defines light animation scores, component contracts, geometry, composition
and scalar controls. Lyte supplies effect generation and device playback. This
implementation adds `kind = "animation"` to the existing version 3 score format;
the historical `format = "recs"` header is unchanged.

## Components and interpretation

`LightType` describes a sampled array with shape **lights × components**. There
must be at least one component. Names and order are significant:

| Light | Example components |
| --- | --- |
| Single dimmer | `white` |
| Tunable white | `warm`, `cool` |
| RGB | `red`, `green`, `blue` |
| RGBW | `red`, `green`, `blue`, `white` |
| Five emitters | `red`, `green`, `blue`, `amber`, `white` |

Names describe components; they do not imply a conversion, spectral calibration,
color temperature, brightness compensation or physical channel address. Each
stream has a uniform component list. Different component sets use separate
outputs and explicit mappings.

`interpretation = "drive"` means normalized component drive values: zero is off
and one is nominal full output. It makes no colorimetric or gamma claim. This
is the contract of the extracted Lyte RGB effects, whose byte RGB settings are
converted by division by 255.

`interpretation = "linear_srgb"` explicitly means linear-light sRGB primaries
and D65 white, with ordered red, green and blue components. Generic operations
can work in this space. Existing Lyte RGB effects cannot simply be relabelled
as linear sRGB. Connections between interpretations are currently rejected;
a calibrated or transfer-function conversion is not implemented.

Frames contain finite numbers. Intermediates may exceed [0, 1]. `Mix` clips at
each mix boundary; `Gain`, `Crossfade`, `Place`, `Reverse` and `ComponentMap` do
not. A byte output boundary clips to [0, 1], multiplies by 255 and rounds to the
nearest integer, ties to even. Component drive values are not audio samples.

## Layout and physical order

`Layout` contains:

- A name, one to three named Cartesian axes and a coordinate unit.
- An ordered list of lights, each with a name and coordinates.
- Optional named regions containing ordered light names.

The list order defines logical frame order. Coordinates describe the arrangement
in space, independently of wiring. Coordinates need not form a grid, be unique,
or be evenly spaced. Regions may overlap. Their ordering can describe a path
around a ring or along a limb. Coordinates do not imply adjacency or a topology
for simulation; an effect's boundary mode still determines that behavior.

`Wiring.order` lists the logical light name for every physical output slot. It
must be a permutation of the layout's names. For a row-major 3 × 2 matrix on a
serpentine string, the physical indexes select logical indexes `[0,1,2,5,4,3]`.
Apply this permutation after composition, once at the output boundary. Reversing
the wiring never reverses an animation's logical coordinates or clock.

`strip()`, `matrix()`, `serpentine()` and `rings()` are authoring helpers that
produce ordinary explicit data. A circle is one ring; concentric circles use
multiple radii and counts. Rings start on positive x and advance counterclockwise
in the x/y plane. The helper creates one named region per ring. Arbitrary
sculptures can supply coordinates directly, including z coordinates.

Wiring belongs to the host installation, outside the score's output contract.
That lets one score play on different physical string orders. Hardware addresses,
network endpoints, channel packing and component order on the wire also remain
host configuration. Wiring alone never converts components or invents geometry.

## A complete two-component score

```toml
format = "recs"
version = 3
kind = "animation"
name = "white_pair"
title = "Warm and cool white"

[[timebases]]
name = "frames"
rate = { numerator = 20 }

[[outputs]]
name = "light"
binding = { light = true }

[outputs.stream]
family = "sampled"
quantity = "light"
timebase = "frames"
components = ["warm", "cool"]
interpretation = "drive"

[outputs.stream.layout]
name = "pair"
axes = ["x", "y"]
unit = "metres"
lights = [
    { name = "left", position = [0.0, 0.0] },
    { name = "right", position = [0.5, 0.0] },
]

[body.operation]
effect = "fill"
values = [0.25, 0.75]
```

The host may use `Wiring(order=["right", "left"])` to address a string wired
from right to left. The score still describes the same left and right positions.

## Effects and composition

`AnimationScore` has one light output, one logical clock, no external inputs,
and an `Animation` body. The body contains an operation and named `Part`s.
Parts use existing `ScoreVersion(path, sha256=None)` values. References are
existing `OutputSelection(name, output)` values. No Python import paths occur
in a score. The common `Composition` resolver checks supplied score records,
optional hashes, cycles, parameter exports and light output compatibility.

`ufor.effects` contains 41 typed Lyte RGB effect descriptions, including each
effect's original settings, defaults and independent validation. Their family
is authoring metadata, not a common parameter vocabulary. Palettes and colors
are lists in interchange, not Python tuples. Byte RGB fields remain byte RGB;
`RandomWalk.color`, gradient masks and other float fields retain their own
existing meanings. The schema describes the exact fields for each effect tag.

Generic operations work with any component count:

| Operation | Meaning |
| --- | --- |
| `Fill` | Repeat a component vector over the output layout. |
| `Mix` | Sum weighted sources and clip each component to [0, 1]. Weights are not normalized. |
| `Place` | Map each child frame, in its logical order, onto named output lights. Unfilled lights are black; placements cannot overlap. |
| `Reverse` | Reverse the logical light order, leaving component order unchanged. |
| `Gain` | Multiply every component by an amount. |
| `Crossfade` | Blend outgoing and incoming sources with linear or smoothstep progress. |
| `Cues` | Activate child parts at scheduled starts and crossfade overlaps. Gaps are black. |
| `ComponentMap` | Multiply each component vector by an explicit matrix. Rows are output components; columns are source components. |

Ordinary sources require identical layouts, components, interpretations and
logical rates. `Place` changes the layout explicitly. `ComponentMap` changes
components explicitly, but does not change interpretation or geometry. For
example, a fourth all-zero matrix row explicitly leaves an RGBW white emitter
off. Ufor never guesses how to extract white or distribute a dimmer across RGB.

`ColorFill` is the extracted byte-RGB effect description; generic `Fill` uses
normalized component values and is the preferred form for new solid lights.

## Timing, state and controls

Logical frames have integer ticks at the declared rational rate. Cue starts,
durations and fades are exact rational seconds and must land on logical ticks.
Do not accumulate floating-point elapsed time. Compute seconds from the current
tick and rate. Output refresh frequency is a host concern, separate from logical
simulation steps. An effect whose original parameter means "per frame" keeps
that meaning at the declared logical rate.

Each named part has independent state. Selecting one part twice shares its
result for that tick; it must not advance twice. Two parts referencing the same
score have separate state. Replaying from the beginning or a valid checkpoint
is required to seek a stateful effect. A seed by itself does not define the RNG
algorithm, floating-point behavior or simulation step sequence across languages.

Cues have increasing starts and ends, with at most two simultaneous cues. Every
cue selects a different part. Children start at local tick zero on activation;
they do not advance before activation. During an overlap both advance, and the
incoming child continues its existing state afterward. Intervals are half-open.
`cue_weights()` returns selected outputs, local seconds and weights. Smoothstep
uses `p*p*(3-2*p)`. `Composition.evaluation_windows()` includes the child history
from local zero needed to answer later requests.

Light parameters reuse `modulation.Parameter`, `Target` and `ParameterExport`.
The reserved local target name is `animation`; the parameter names a numeric
operation field, for example `{name="animation", parameter="amount"}` on `Gain`.
The body cannot also contain a part named `animation`. Exports can instead name
a child part and forward its public parameter. Structured fields such as palettes
and component matrices are edited as typed data, not float parameter overrides.

Autonomous controls have part scope and use either shared `envelope.Curve` or
`LFO` data. Curves reuse `Segment` and its exponential curve calculation; they
can hold or repeat, with arbitrary finite scalar levels including gains above
one. Trigger/release `Envelope` still validates its original normalized domain.
Light LFOs require seconds, part scope and free reset. Delay and fade weights use
the existing modulation rules, including the neutral value for multiplication.
`operation_at()` evaluates controls and revalidates the resulting settings.
An integer field must still receive an integer-valued result.

## Conformance and current boundary

`conformance/lights/` includes wiring and composition vectors, explicit ring
geometry, and a complete miniature mirrored-ripples/aurora score collection.
`brightness.toml` wraps that collection in a repeating shared gain curve with
a public brightness parameter. `light_math.py` supplies small standard-library
reference calculations over already supplied frames. It has no renderer state,
NumPy dependency, transport, scheduler, device discovery or effect generation.

Tests establish interchange, validation and these mathematical semantics. They
do not establish cross-language equivalence for Lyte's stochastic simulations.
That requires renderer-generated reference frames, specified RNG behavior and
numerical tolerances in the Lyte port. See [port-lyte.md](port-lyte.md).
