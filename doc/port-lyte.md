# Port Lyte to Ufor light scores

## Status and scope

Completed on 2026-09-10. Lyte pins Ufor commit
`0b88a111b9b02dd696716581dfa0cc68e8cf235c` in Lyte commit `5d6ec33`, and the
renderer, library selection, examples, preview, installation integration and
tests were ported in Lyte commit `905f894`, with strict Ufor ownership of the
renderer setting models completed in fixup commit `b8b9b28`. The old
composition reader and Python-path authoring format were removed without a
compatibility path.

The completed Lyte checks were 331 passing tests with two opt-in skips, Ruff,
formatting, Ty, pyupgrade for Python 3.13, and `git diff --check`. Physical
Twinkly and Art-Net output remain separate deployment validation.

Read [library.md](library.md), [light-format.md](light-format.md), `ufor/lights.py`,
`ufor/light_animation.py`, `ufor/effects.py` and `ufor/light_math.py` first.
`schema/scores.json` includes the new animation kind. The existing score format
version is still 3. There is no Ufor dependency on Lyte or NumPy.

Additional work beyond the prompt: None. Audio waveform generation, samplers,
new transport protocols, dynamic DMX fixture effects and live control-input
schemas are outside this port.

## 1. Add the dependency

Pin Lyte to a Ufor revision containing both light scores and the implemented
library reader (`01d8144` or later). Follow the sibling projects'
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

## 3. Replace the file model with the library reader

Replace `show.AnimationSpec`, `MixerSpec`, `impl` strings and recursive Python
construction in `show.build_show_graph()` with Ufor scores. Keep physical device
and run configuration in Lyte. Those host records should select a score using
a library selector, its named light output, public parameter overrides, and a
wiring description. The library configuration path is a host option.

Call `ufor.library_files.read_library(config_path)` explicitly during preparation.
Omit the path to use `~/.config/ufor/library.toml`; an explicit configuration
replaces the default rather than merging with it. Roots are registered in that
file and resolved relative to its directory. Reading creates nothing. Use
`create_library()` only for an explicit library-creation action.

Use `library.find(selector)` for browsing, `library.resolve(selector)` for one
usable entry, and `library.composition(selector, parameters)` for its prepared
graph. Ufor owns discovery, file hashes, reference binding, preset normalization
and cycle recovery. Do not recreate those steps or manually assemble another
`ScoreRecord` graph. Use the resolver's prepared part paths for runtime state.
Validate the selected light output and every renderer capability before opening
a device; a browseable score such as a tuning is not necessarily playable by Lyte.

Selectors use literal library/name/tag/address matching, with no quoting,
escaping or patterns. An omitted library searches every registered root; never
prefer the current library or choose the first match. Extensionless addresses
can be ambiguous. Authored parts use `ScoreVersion(selector=...)`; its existing
relative `path` form still resolves from the referring file within the library.
Optional hashes verify exact file bytes without selecting a fallback.

Display `library.diagnostics`, including referring fields and cycle paths.
Independent entries remain usable when another entry is rejected or blocked.
Do not fail the entire browser because an unrelated score failed, and do not
silently omit an unavailable part of the selected composition. Refresh through
an explicit new read, without adding a watcher or retry loop.

Keep `entry.score` as the authored declaration. `entry.resolved` and
`library.records` contain normalized descriptions for execution; never save their
synthetic `dependency_0.toml` paths as authored references. For inherited assets
or implementations, follow `entry.content_origin` to the base entry and its
registered root/address. Presets retain their own metadata and file hashes.

### Python score implementations

The reader accepts exactly one locally defined Ufor score subclass per Python
file. Existing Lyte `Animation` classes do not meet that contract unchanged.
Keep built-in rendering behind the effect registry, and define the Lyte runtime
contract for custom Python score classes during this port. Use the retained
`entry.python_class`, or the content origin's class for an inherited implementation,
without guessing behavior from method names. Validate that contract before output.

The reader validates native descriptions from class defaults without calling
constructors or playback methods. Dependencies must remain declared in score
fields. Module code and default factories do execute; configured Python libraries
are local user code, not sandboxed plugins. Do not restore arbitrary `impl` paths
in TOML or add roots to `sys.path`. Keep helper modules outside the score root.

Update all callers together:

- `show.py`: loading, graph construction, preflight and target creation.
- `animate/build.py`: replace composition-file/source selection with the library
  configuration and score selector, using the same preparation path.
- Preview paths that call the same builder.
- `installation.py`: replace `PixelProgramSpec.impl/sources/params` and its
  construction of `show.AnimationSpec` with the same library selection path.
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
Represent named variations of exported scalar settings as `PresetScore` entries.
Let Ufor apply chained preset defaults and caller overrides, including range
validation. Presets are not arbitrary settings merges; palettes, seeds and
structural variations belong in typed animation scores unless explicitly exposed
through a suitable public parameter contract.
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
Register the `conformance/lights` directory in a library configuration and select
`/main.toml` to use this graph through the reader. Then replace
`examples/composition.toml` with library scores and update its
250-light layouts and placements explicitly. Replace the pixel program in
`examples/installation.toml` using the same library selection path.

Use `conformance/library/library.toml` to verify selectors and presets: its
`pond` score composes two preset variations. Keep installation/device records
outside score roots, since every discovered `.toml` file is a score candidate.

Tests for the port should establish:

- Preview and device preparation select the same library entry and honor preset
  defaults and caller overrides without duplicating library resolution tests.
- Library diagnostics remain visible; unrelated failures do not prevent playing
  a valid selection, while missing, ambiguous or blocked selections fail before output.
- Python score implementations use the explicit host contract and retain separate
  runtime state per prepared part, including when selected through presets.
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
