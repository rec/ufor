# Port Lyte to Ufor light scores

## Status and scope

The Ufor side is implemented. **Lyte has deliberately not been changed.** The
user explicitly deferred that work to another context and discarded backward
compatibility for existing animation files. Do not add compatibility readers or
keep Python-path and Ufor authoring formats in parallel.

The extraction was based on Lyte commit
`e6131dfbaf2fe9e134227793352eaa2fc9cf823f`. Re-read Lyte's current instructions,
worktree and source before editing; it may have advanced since that revision.

Read [light-format.md](light-format.md), `ufor/lights.py`,
`ufor/light_animation.py`, `ufor/effects.py` and `ufor/light_math.py` first.
`schema/scores.json` includes the new animation kind. The existing score format
version is still 3. There is no Ufor dependency on Lyte or NumPy.

Additional work beyond the prompt: None. Audio waveform generation, samplers,
new transport protocols, dynamic DMX fixture effects and live control-input
schemas are outside this port.

## 1. Add the dependency

Pin Lyte to the Ufor commit containing this work. Follow the sibling projects'
local editable-development arrangement, without publishing a local filesystem
path as the installable dependency. Commit `pyproject.toml` and `uv.lock`
separately from implementation changes. Do not add GitHub workflows.

## 2. Make Ufor the owner of animation settings

Lyte's current frozen `Animation` subclasses combine configuration and methods.
Replace their local configuration fields and validators with the corresponding
Ufor effect descriptions. Retain rendering methods and dedicated mutable state
classes in Lyte. Do not copy the Ufor fields into a second model.

An explicit renderer registry should map the `effect` tags in `ufor.effects`
to installed Lyte renderer classes. Populate it from the known effects, without
loading arbitrary Python import paths from score data. Unknown or unsupported
effects must produce a clear capability error before device output starts.

The 41 RGB tags correspond to the snake-case filenames under
`lyte/animations/{patterns,fields,events,simulations}`. The named variants
`rainbow_cycle` and `white_twinkle` have their own descriptions. `family` is
class metadata. Strip the effect discriminator when constructing a runtime
object that does not inherit its description.

Interchange collections use lists. Audit helper signatures and tuple-specific
operations when replacing settings; do not require tuple data in scores.
Retain the existing byte-color conventions for extracted RGB algorithms.
Prefer generic `Fill(values=...)` for newly authored solid lights; translate
old `ColorFill.color` by dividing each byte component by 255 when replacing
the examples.

## 3. Replace the file model and use the existing resolver

Replace `show.AnimationSpec`, `MixerSpec`, `impl` strings and recursive Python
construction in `show.build_show_graph()` with Ufor scores. Keep physical device
and run configuration in Lyte. Those host records should select a score path,
its named light output, and a wiring description.

The host loads score files, computes hashes when pins require them, and supplies
`ScoreRecord(score, paths, sha256)` objects to `Composition`. Relative paths are
resolved relative to the referring score, not the working directory. Use the
existing resolver's prepared part paths; do not build a second name or reference
system. Validate the complete selected graph before opening a device.

Update all callers together:

- `show.py`: loading, graph construction, preflight and target creation.
- `animate/build.py`: the composition-file/source options and builder.
- Preview paths that call the same builder.
- `installation.py`: replace `PixelProgramSpec.impl/sources/params` and its
  construction of `show.AnimationSpec` with the same score loader.
- CLI descriptions, examples and tests of the old file parser.

Keep a single construction path shared by preview and device playback.
Remove obsolete parser and Python-path-resolution tests, replacing them with
tests of the new behavior. Preserve independent device/run configuration where
useful, but do not retain two ways to describe an animation graph.

## 4. Implement component-independent composition and layouts

A render context must carry the selected `LightType`, not just `led_count`.
Frames have shape `(len(layout.lights), len(components))`. Generalize validation,
black frames, placement, mixing, gain, reversal and fading to this shape. Require
finite values and contiguous float32 arrays at Lyte's runtime boundary.

The RGB algorithms still require red/green/blue drive outputs. Do not pad,
truncate, rename or silently convert their channels for monochrome, warm/cool,
RGBW or other devices. Use an authored `ComponentMap`; its matrix is an explicit
decision about the destination components. Optimized NumPy composition must
match Ufor's reference calculations.

Replace positional segment offsets with `Place` mappings to named lights.
Children retain their own logical layouts, and each placement maps child order
onto the ordered target-name list. This supports noncontiguous selections and
named regions, not just intervals on a string.

Use `Layout` coordinates for spatial previews. A matrix is one geometry, not the
required geometry. Test irregular positions, circles and concentric rings.
Existing strip effects use logical order unless the algorithm explicitly reads
coordinates; giving them a two-dimensional layout does not make them 2D effects.

Apply `Wiring.indexes(layout)` once at the final physical-output boundary.
For a serpentine matrix, render normal row-major geometry, then permute rows
of the frame into string order. Preview the logical geometry, and optionally
show wiring as an overlay. Do not apply the wiring to intermediate effects or
apply it twice through both preview and driver code.

Keep measured geometry separate from guessed wearable mappings and actual
hardware channel packing. A light-count mismatch is not authorization to stretch
the score's geometry. Decide any explicit host adaptation before playback.
Wiring changes neither component meaning nor component order.

## 5. Preserve timing and state ownership

Maintain one state per prepared part path and cache its output per logical tick.
Repeated selections of that part share the result. Separate parts using the same
score create independent state, even when their seeds and outputs match.

Replace floating-point accumulated elapsed time with integer ticks at the
score's logical rate. Translate to seconds only for an algorithm calculation.
The existing `state.fps` should represent this logical rate. Device pacing may
repeat or omit delivery of frames, but must not change the simulation step
sequence. Seeking requires replay or a valid state checkpoint.

Map the current compositions as follows:

| Lyte | Ufor |
| --- | --- |
| `Segments` and `Placement(start, led_count)` | `Place` and ordered target light names |
| `Mix(sources, weights)` | `Mix` with `WeightedSource` selections |
| `Reverse` | `Reverse`; reverse lights, not components or time |
| `Crossfade` and `Fade` | `Crossfade` and exact rational `Fade` |
| `Sequence` and `Cue` | `Cues` and named independently activated parts |
| `Envelope(points, repeat)` | `Gain` controlled by shared `envelope.Curve` |

For an old envelope, the first gain becomes `Curve.initial`. Each following
point becomes a `Segment` whose duration is the difference between point times
and whose target is that point's gain. A single constant point can use a
nonrepeating zero-duration segment. Repeating curves need positive total duration.
Do not divide gains above one into a normalized envelope.

Cue-local time starts at activation. An overlap advances both children, and the
incoming child's state continues afterward. Never recreate that state at the end
of a fade. Give repeated cues separate part names. Gaps are black. Follow
`cue_weights()` and half-open intervals, without floating-point epsilon tests.

Preserve clipping at every `Mix` boundary. Flattening nested mixes is incorrect.
Crossfades, placement and gain preserve intermediate values outside [0, 1].
Only final byte encoding clips again. Test rounding separately from float math.

## 6. Wire in shared parameter controls

Use `Composition.parameter_contract()` and prepared public parameter values.
Resolve local exports to their `animation` target fields before calling
`operation_at(body, local_seconds, local_parameters)`. Child exports have already
been propagated by the resolver. `animation` is reserved as the local target
name, so it cannot also name a child part.

Reuse Ufor's existing modulation evaluation and shared curve/LFO calculations.
For autonomous light LFOs use seconds, part scope and free reset. Preserve their
delay/fade weight separately; multiplying the raw LFO value by that weight too
early changes the neutral value of multiplicative modulation.

Reconfiguring scalar settings must preserve runtime state. Some algorithms use
parameters only when constructing state; expose them only when the renderer can
honor changes, or report them as construction-only host capabilities. Changing
particle counts or seeds mid-simulation must not silently reset unrelated state.
Palettes and matrices remain typed settings, not float overrides.

To expose a mixture weight, put a named `Gain` part before that mix input and
export its `amount`. This uses the existing scalar parameter address without
introducing an index-based path into a list of weights.

External MIDI/breath/note bindings in Lyte may drive host parameters. This Ufor
profile deliberately has no live input contract yet; do not imply those events
are already persisted or replayable through `AnimationScore`.

## 7. Migrate examples and verify the renderer

`conformance/lights/main.toml` is a complete small version of the existing
mirrored-ripples/aurora example. It has six lights per half and twelve in the
combined output. `brightness.toml` adds an exported gain with a repeating curve.
Use this graph first, then replace `examples/composition.toml` and update its
250-light layouts and placements explicitly. Replace the pixel program in
`examples/installation.toml` using the same loader.

Tests for the port should establish:

- Every extracted effect is constructible from its Ufor description.
- Preview and device playback use the same logical frames.
- One-, two-, three-, four- and five-component frames survive generic composition.
- Serpentine wiring matches `layouts.json`; rings and arbitrary coordinates
  display without assuming a rectangular matrix.
- `operations.json` agrees with the optimized renderer; nested clipping, gain
  above one, fades and inactive cues retain their specified behavior.
- Reusing one part does not advance it twice; separate parts remain independent.
- Delayed cues begin at local zero, crossfades preserve state, and replay agrees
  with sequential rendering at the same logical rate.
- Unsupported component contracts fail before hardware output.

Use fixed seeds and logical rates to add language-neutral output fixtures for
representative time-driven, random and simulation effects. Record RNG algorithm,
initialization and step order, float precision, reference revision and numerical
tolerance. Current Ufor tests cover composition math and schema, not exact
stochastic rendering equivalence across languages.

During source review, `LogGradient` was found to normalize by `max-min` without
handling a constant field (including a one-light layout). Resolve this explicitly
and test it during the renderer port; Ufor's finite-frame rule will reject NaNs.
Do not interpret successful model validation as proof of every renderer's edge
cases. Run Lyte's required checks; physical device verification is a separate
step and must be reported separately from automated results.
