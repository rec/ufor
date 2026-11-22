# Rust implementation

The Cargo workspace implements checked pitch numbers, expression evaluation,
`Computed`, `RatioTable`, `IntervalPattern`, `FrequencyTable`, `Tuning`, and the
`TuningScore` envelope in `crates/ufor`. JSON/TOML interchange supports those
definitions. Python bindings and WebAssembly remain
outside this implementation.

## Score coverage

These are the version 4 kinds in Python's `ScoreValue` union. The Rust
`codec::parse_score` and `codec::score_text` APIs cover the rows marked
JSON/TOML score. Preparation APIs accept the indicated body or resolved
declarations.

| Kind | Rust coverage |
| --- | --- |
| `tuning`, `scale`, `oscillator` | JSON/TOML score and standalone musical definitions |
| `envelfo` | JSON/TOML score, generator definitions, parameter materialization, and binding checks |
| `sequence` | JSON/TOML score, ordered event body, and sequence playback planning |
| `automation` | JSON/TOML score, control curves, and scalar evaluation |
| `synth_instrument` | JSON/TOML score and standalone body, including public ports, timebases, and oscillator, FM, noise and Yamaha voices |
| `instrument` | Sampler preparation APIs for asset inventory, authored slot predicates and settings, selection, and traversal |
| `performance_binding` | JSON/TOML score, MIDI channel assignments, and contextual preparation against supplied controls and resolved tunings |
| `arrangement` | `parse_control_clip` prepares automation placement and exact source requests |
| `animation` | Standalone envelope curves and LFO definitions |
| `arpeggiator`, `binding`, `broadcast`, `fixture`, `preset`, `recording`, `slideshow` | Python score models |

## Preparation and evaluation APIs

`codec::parse_yamaha_patch` and `codec::yamaha_patch_text` read and write the
hexadecimal edit buffers used by DX7, TX81Z, and WT11 voice declarations.
DX7 supports both packed and unpacked voice data. TX81Z and WT11 preserve the
additional operator buffers, including WT11's aftertouch record and reserved
bytes. `yamaha::Patch::parameter_diagnostic` reports invalid decoded parameters
in front-panel operator order. Structurally valid buffers retain their raw
bytes even when they have a diagnostic. The patch codec covers the Yamaha
discriminator and edit buffers within an authored voice.

`codec::parse_synth_instrument` and `codec::synth_instrument_text` handle
complete synth instrument bodies. For Yamaha voices this includes DX7
performance controls, per-voice modulation targets, and TX81Z shared outputs
and LFO owners. The shared preparation record budget covers the voice
definitions and group declarations together.

`codec::parse_score` and `codec::score_text` handle the version 4 synth
instrument document. They validate its performance input, sampled audio
output, timebase references, and mono voice routes to the declared channels.
Shared TX81Z output routes are checked against the same audio port. The
score envelope and instrument body share one preparation record budget.

`scala::parse_scala` and `scala::scala_text` interchange repeating ratio
tables. Imports use an ASCII integer pitch count, implicit unison and the
last pitch as the repeat ratio. A decimal pitch is read in cents. Exports keep
exact ratios as fractions and write approximate pitches to twelve decimal
places in cents. Import uses the tuning table entry and document text
limits. The [shared Scala cases](../conformance/scala.json) verify both
languages against the same examples.

`codec::parse_scale` reads scale definitions and `Scale` maps note names,
note numbers and tuning coordinates. Rust supports whole-step and half-step
accidentals, compact interval strings, and integer steps with the portable
semitone, cent and octave aliases. Rust uses ASCII octave numbers in note
names. Scale preparation permits up to 10,000 spellable positions and uses
the document character limit for generated spellings. Zero intervals and
partial note filters can be stored and edited. Naming or tuning lookup
returns an error when the scale has no playable positions.
The [shared scale cases](../conformance/scale.json) cover negative notes,
filtered scales and aliases.

The crate also implements [modulation routes, control declarations and binding
value types](rust-modulation.md), including scalar reference evaluation and
explicit reporting of unresolved generator/processor references. Full
instrument/effect preparation and runtime integration remain with consumers.

The [generator-definition module](rust-envelfo.md) adds LFO, Envelope, SampleHold,
Stages, Patch and unresolved reference models, portable JSON/TOML bodies,
configurable preparation limits, graph ranges and captured-approach mathematics.
Envelfo scores, public rate parameters and materialization are implemented, as
are generator-aware binding checks with typed outstanding requirements for
unresolved references, followers and target compatibility.

`automation::Automation` evaluates gain, frequency, and gate curves at signed
64-bit ticks in the declared timebase. Use `codec::parse_automation` for a standalone
body or `codec::parse_score` to validate its control output and timebase together.
The [automation format](automation-format.md) defines the scalar and timing rules.
`automation::placement::ControlClip` places a resolved part-scoped numeric
automation output on another clock. It validates exact placement and returns
the source interval needed to reconstruct the curve for a render window.

`envelope::curve_progress` evaluates the normalized exponential interpolation
used by authored envelope segments. Positive and negative coefficients use
stable exponential forms, with exact endpoints and linear interpolation when
the coefficient is zero.
`codec::parse_curve` and `codec::curve_text` read and write standalone
`envelope::Curve` bodies. `Curve::at` takes a nonnegative rational distance from
activation. It uses the durations' magnitudes, leaving clock conversion to the
caller. The evaluator checks the signed 64-bit rational domain and finite
scalar result. The budget counts the curve and its segments. The
[shared curve cases](../conformance/envelope-curves.json) cover jumps, wrapping,
final hold and signed exponential interpolation.

`oscillator::phase_at_frame` computes transport-synchronized starting phase in
sample-rate units. It reduces the exact frame-frequency product modulo the
sample rate before rounding to binary64. Whole frames retain signed 64-bit
precision and fractional origins retain their binary64 value.
`oscillator::sample_at_angle` evaluates sine, square and triangle render
samples with a prepared binary64 duty value. Enge uses it for block and
persistent synth oscillators and FM graph operators.
`oscillator::advance_phase` carries the compensated-addition error through
phase wraps and block boundaries. Both values are in sample-rate units.

[Portable SoundSettings](rust-sound-settings.md) adds processing declarations,
base target resolution and contextual validation for the settings body.

`samples::slots::PreparedSlots::from_json` reads the slots and groups
directly from an authored sampler body. It prepares the eligibility
predicates and resolves each slot's settings and selection with its group.
It preserves nested declaration order for decoding with SoundSettings.
`samples::inheritance::resolve_slot_settings` applies the same inheritance
rules to individual setting fragments.
The [shared cases](../conformance/slot-settings.json) cover inherited
categories, explicit resets, and selection opt-out.

`samples::routing` builds an explicit matrix in input and output channel
order. It also resolves native and Sfizz pan laws for sampler mono pan and
stereo balance. Sampler mono pan uses center-relative scaling of authored
routes. The [shared vectors](../conformance/channel-routing.json) cover
layout order, signed gains, and the pan endpoints.

`codec::parse_oscillator` and `codec::oscillator_text` handle oscillator
declarations in JSON and TOML with a checked exact duty cycle. The common
score codec also reads and writes version 4 oscillator scores. The oscillator
provides key-scaled linear gain, correctly rounded binary64 duty for
renderers, and scalar sine, square and triangle shape observations.
The [shared cases](../conformance/oscillator.json) cover gain, asymmetric
and endpoint duty cycles, and rounding near a discontinuity.

`synth_pitch` realizes routed oscillator pitch from onset `pitch_hz` and
cents. FM multiplies the onset pitch by the operator ratio before applying
the sum of voice and operator cents. Both functions reject nonfinite or
nonpositive rendered frequencies with allocation-free errors. The
[shared vectors](../conformance/synth-pitch.json) cover both calculations.

`ufor::fm::Fm` validates the authored two-to-six operator phase-modulation
graph, its operator Envelopes, and its edge and carrier references. It exposes
the current-sample operator order, carrier position, and edge endpoints in
declaration order. It also resolves operator ratios and tuning, edge indices,
and carrier level from the owning declarations. `FmTopology` groups incoming
edges without changing their summation order. It reads delayed samples from
edge history and captures feedback after each output frame. Use
`codec::parse_fm` and `codec::fm_text` for JSON or TOML FM bodies. This API
provides graph facts for consumer preparation. The renderer owns sample-rate
conversion, voice state and execution.

`ufor::effects::Processor` reads all authored effect processor kinds through
`codec::parse_effect_processor`. It resolves modulation units, defaults, and
parameter domains from the authored definition, including named filter stages,
compressor bands, and mixer inputs. Use `Processor::validate_parameters` to
check combined base-delay and depth ranges. Matrix and convolution declarations
have no modulation targets.

`codec::parse_effect_topology` reads the authored graph fields for scope,
owner, inputs, processors, connections, output, modulation, and bindings.
It checks connections and named layouts, preserves Python's sorted order
within each dependency layer, and includes follower edges in latency
alignment. `Topology::latencies` uses checked 64-bit frames at the host
sample rate. Enge resolves assets, assigns runtime slots, and prepares DSP.

`codec::parse_effect_action` and `codec::parse_effect_action_batch` read effects
automation, bypass, capture, freeze, and lifecycle actions. A topology checks
processor capabilities, authored target bounds, and input names. Batches require
one frame and strictly increasing ordinals, and callers supply their batch
capacity. Enge retains frame windows, queue admission, and state-dependent
checks.

`codec::parse_tempo_map` and `codec::tempo_map_text` handle host-supplied tempo
maps with exact rational seconds, beats, and BPM. `control::tempo::TempoMap`
distinguishes transport position from elapsed running beats, resolves
quantized targets, and reports seeks that invalidate pending beats. Enge uses
its exact frame points for native beat-clock preparation.

`control::schedule::schedule_commands` resolves quantized EnveLFO command
coordinates on a host tempo map. It rounds dispatch times up to frames,
places moved commands after authored events on the destination tick, and
drops pending commands invalidated by a seek or an unreachable beat.
The [shared cases](../conformance/command-schedule.json) cover these rules
including a tempo change and multiple commands arriving on the same tick.

`events::prepare_performance` applies that scheduler to typed performance
events, checks duplicate coordinates and validates controls against the
instrument's declarations. Its indices refer to the original event slice
and its coordinates give the dispatch order. Ordinary events need no clock.

`codec::parse_sample_slice` and `codec::parse_sample_playback` read sample
traversal declarations. `samples::playback::Slice` validates native frame
intervals, loop crossfades, and resolved playback against decoded asset length.
`samples::playback::onset_gain` combines key and velocity crossfade weights with
instrument, slot and variation decibels. Control fades remain time-varying.
Sampler batching uses `samples::playback::maximum_tuning_cents` to select each
layer's declared tuning maximum or its static tuning. If the combined bound
overflows, `maximum_sample_step` selects one-frame batches for finite traversal.
Loop repeat limits and the number of additional plays use unsigned 64-bit
counts. The renderer owns the audio, traversal state, and interpolation.
`codec::parse_sample_mapping` validates authored note and velocity ranges and
the sample's reference frequency. `Mapping::pitch_ratio` combines resolved
`pitch_hz` with tuning and variation cents. Sample-rate conversion remains a
renderer operation.

`codec::parse_sample_crossfade` reads key, velocity, and control layer fades.
The shared gain curve supports linear and equal-power fades with exact endpoint
weights. Hosts retain control smoothing, event routing, and layer selection.
`Crossfade::prepare_control` resolves a live fade against the instrument's
control declarations, validates both endpoints, and converts smoothing to
signed 64-bit rational frames from the decimal seconds magnitude. Enge uses the
result to prepare its live sampler control tables.

`codec::parse_sample_eligibility` prepares ordered sampler slot predicates.
`samples::eligibility::Eligibility::matching_slots` filters them using the
trigger, note and velocity, articulation, resolved controls, held keys,
previous key, sequence count, and random draw supplied by the caller.
The [shared cases](../conformance/sample-eligibility.json) cover inclusive
note and control bounds, half-open random ranges, and sustain event keys.
Python trace preparation supplies these event facts and owns voice lifecycle.

`codec::parse_articulations` reads ordered articulation IDs, keyswitches and
disjoint control ranges. `Articulations::validate_controls` checks the range
endpoints against instrument control declarations. Enge prepares the native
sampler's latched keyswitch lookup through `Articulations::latched_keys`.
A switch can clear the current articulation or consume the onset. The trace
stores the resulting latch independently for each part.

`codec::parse_voice_eligibility` prepares mappings for synth-family voices.
It shares the sampler's inclusive note and velocity predicates and matches
the declared event key for sustain triggers. The
[shared cases](../conformance/voice-eligibility.json) cover layering in
declaration order, boundary velocities and synth sustain mappings.

`codec::parse_synth_voice_templates` reads a `voices` list containing mapped
voice metadata. It validates route names, finite gains, exact minimum holds,
and unique route, choke and articulation entries. Enge passes this
projection to its native trace matcher. The preparation budget counts the
root, voices, routes, chokes and articulation references.

`codec::parse_synth_voices` reads mapped oscillator, white-noise and FM voices
with their flat SoundSettings fields. Oscillator and noise voices use the
voice-scoped unipolar envelope in `SynthVoice::settings()`. FM uses its
operator envelopes. `SynthVoice::resolve_target` resolves FM graph targets
against the voice's own graph and delegates the rest to SoundSettings.
The preparation budget covers the template, source and settings together.
`codec::parse_synth_instrument` adds the instrument's controls, voice policy,
sustain declaration and articulations to that budget. It validates binding
domains against the controls, note-key coverage against the mappings, and
articulation and choke references against the instrument. The prepared body
exposes the initial sustain state and ordered voice matching used by enge.

`samples::selection::Sequence::advance` returns the next take and partition
state for cycle, seeded random, and shuffle. It preserves the portable
SHA-256 draw and selection snapshot fields. The
[shared vectors](../conformance/selection.json) cover choices and continuation
after restoring the partition. Rust uses a checked unsigned 64-bit counter.

`codec::parse_sample_take_selector` prepares named selection groups and
the resolved selection and take identity of each slot. Given eligible slots
in declaration order, `TakeSelector::select` keeps ungrouped slots first,
then advances each eligible group in selection declaration order. Slots
sharing the chosen take stay together. The snapshot contains partitions in
order of their latest successful choice, matching the Python trace format.
The preparation limit counts the root, selection declarations and slots.

`samples::variation::DrawEvent` derives the shared random-range draw for
an event. `Variation::resolve` uses that event and the supplied take or slot
identity to resolve independent delay, frame offset, pitch and gain draws.
The portable API uses signed 64-bit ticks and frame offsets, unsigned 64-bit
seeds and ordinals, and binary64 scalar bounds in canonical units.
The [random-range](../conformance/random-ranges.json) and
[variation](../conformance/variation.json) cases pin both draw contracts.

`codec::parse_voice_admission` reads the selected batch and its active-voice
context. `Admission::retirements` returns the ordered trace actions for
chokes, per-part voice pools in name order, and the global voice policy.
The [shared case](../conformance/voice-admission.json) covers choke
precedence, same-key retriggers and oldest-first retirement across parts.

`codec::parse_choke`, `parse_voice_policy`, and `parse_voice_pool` read the
same declarations used in admission requests. Fade mode requires a positive
duration, which can use portable seconds units, and each voice limit must
be positive. Enge's existing native admission path uses these validators
when decoding each batch.

`codec::parse_voice_release` reads a key release or a per-part sustain
change with its ordered trigger state. `ReleaseRequest::plan` identifies
physical and logical releases and pedal transitions. Hosts use the returned
indices to apply release layers in order, updating the active voice state
after each layer. The [shared cases](../conformance/voice-release.json)
cover deferred releases, duplicate releases, part isolation and threshold
crossings.

`codec::parse_sustain` reads the named sustain control and its positive
threshold. `Sustain::initially_pressed` checks the resolved unipolar control
declaration and compares its default to the threshold, including equality.
Enge uses it to initialize each part's pedal state when preparing native
sampler and synth-family traces.

`voice_start::prepare_values` applies a voice's frequency offset to
resolved pitch and derives EnveLFO and optional noise stream keys from the
performance seed and voice ID. It preserves an absent pitch and rejects
arithmetic overflow. The [shared vectors](../conformance/voice-start.json)
pin both hash domains and the existing EnveLFO graph identity format.

`codec::parse_slot_playback` resolves slot direction and mode overrides against
instrument defaults. The prepared declaration sums slot and variation delays
with checked 64-bit rational arithmetic and rounds up once to an output frame.
JSON preserves totals through `2^64` plays by storing the additional-play
count. TOML integers use their signed 64-bit format domain.

`codec::parse_sample_inventory` reads sampler metadata from JSON or TOML.
It accepts `timebases`, `assets` projected to name and audio description,
`slices`, and `output` projected to timebase and channel names. It checks
references, native frame extents and channel layouts. The preparation
budget counts the root, timebases, assets and slices.
`Inventory::integer_rates` checks the supplied decoded shapes against the
referenced assets and resolves the output and native rates. Both rates must
declare a denominator of one for that preparation profile.

`codec::parse_timebase` reads a named physical timebase. Rates have positive
signed-64-bit integer components and retain their declared denominator.
`time::convert_tick` converts absolute coordinates exactly and rounds once
with ties to even. Negative coordinates are supported and a rounded result
outside the signed-64-bit domain returns an error. The
[shared vectors](../conformance/physical-time.json) include conversions
whose exact intermediate products exceed 128 bits.

`time::duration_frames` converts nonnegative seconds at a positive integer
sample rate to a checked rational frame duration. Enge uses it to prepare
fractional minimum holds for its persistent synth, FM and noise renderers.

`time::PpqnClock` converts ordered MIDI file ticks into sample frames at an
integer rate. It keeps elapsed time exact across tempo changes and rounds
each absolute frame once, with ties to even. Pass the new tempo with its
event tick in microseconds per quarter note. It applies to subsequent
intervals. The clock accepts synchronous PPQN timing and leaves file decoding
and MIDI dispatch to the host.

`codec::parse_midi_bindings` takes an authored performance binding score and
a separate context document in the same format. The prepared bindings retain
part order and map primitive MIDI values to configured control ranges,
including both asymmetric bend endpoints. The host resolves the instrument
and tuning references. When the host supplies a `controls` map, preparation
checks every mapping against those declarations. The `tunings` map uses
relative paths or `selector:` followed by the canonical selector as keys.
Preparation decodes each referenced tuning body once and makes it available
by channel. The record limit covers the authored score, reference records,
supplied control declarations, and used tuning definitions.
`performance_binding::HeldNotes` owns one source's held-note queues,
admission limit, and trigger IDs. It resolves a note against the supplied
tuning or 12-tone equal temperament with A4 at 440 Hz. It pairs releases
using the supplied channel policy and requires explicit restart after loss.
Restart retains the trigger ID counter. The host supplies event coordinates
and order.

`codec::parse_performance_event` and `codec::performance_event_text` handle
trigger, release, scoped control change, LFO change, and Envelfo change
records in JSON and TOML. Performance ticks are signed 64-bit. Ordinals are
nonnegative and use unsigned 64-bit in Rust, with TOML limited to its signed
integer domain. Beat divisions are positive exact rationals. The
[shared cases](../conformance/performance-events.json) cover command payloads,
control addressing, and pitch units.

`codec::parse_performance_payload` validates the same records without
coordinates. `PerformancePayload::validate_controls` checks trigger overrides
and control changes against host-supplied instrument declarations. Enge uses
this payload boundary in native instrument traces and retains its existing
host event coordinates.

`codec::parse_stored_event` also reads captured MIDI bytes, complete UMP
packets, OSC packets with decoded messages and diagnostics, and key events.
It preserves the capture payload without interpreting it as performance
instructions. Decoded OSC integer arguments use signed 64-bit values.
JSON preserves null OSC arguments, and TOML export rejects them because
TOML has no null array element.

`codec::parse_event_sequence` checks unique ordinals, order by tick and
ordinal, and membership in the half-open sequence extent. The extent is
independent of the event count. Version 4 sequence scores use the same body
and validate the declared timebase and event output kinds. The preparation
budget counts the root and events, plus timebases and output declarations
for a score. Python and Rust exercise the
[shared sequence cases](../conformance/event-sequence.json).

`codec::parse_sequence_selection` reads a nonempty half-open source interval,
a destination start tick, a positive repetition count, and the active-note
policy. `playback::state_at` reconstructs triggers and controls strictly before
the requested tick. `playback::plan_playback` validates ownership through the
selected end and checks that every destination boundary fits in signed 64-bit
ticks. Its iterator builds one repetition at a time.

Each repetition carries initial instrument and part controls, retimed
performance events, captured records, and explicit boundary releases.
Trigger identities are scoped by the selection name and iteration.
The host applies controls, events, and cleanup in that order. Captured
records retain their source ordinals and are available for inspection.
The [shared playback cases](../conformance/sequence-playback.json) cover
both active-note policies, control ordering, and cleanup across parts.

`samples::cursor::Cursor` advances a validated slice in native frames. It
handles pending loop boundaries, release, overlap taps, whole plays, and end
fades. The host can copy the cursor for interpolation lookahead and restore a
`CursorState` for continuation. `Cursor::read_plan` prepares interpolation
knots and their loop overlap weights. The host can reuse the plan across
channels by supplying decoded values by native frame index.
`Cursor::start_offset` combines signed asset alignment with variation measured
in the initial playback direction. `Cursor::offset_start` marks exhaustion
when the resulting position lies outside the slice.
`Cursor::active_prefix` bounds control batches with the
maximum cursor step, the remaining traversal, and any latched end fade.
`Cursor::advance_with_release` splits a step at a fractional frame using a
signed-64-bit rational. Each side is rounded once from its exact share of
the binary64 step. A release coincident with an uncommitted boundary takes
effect before the cursor chooses whether to turn or wrap.
The playback module applies layered cents with `tuned_pitch_ratio` and
converts a ratio into cursor units with `sample_step`. Both check the
positive finite result. The [shared playback cases](../conformance/sample-playback.json)
exercise the conversion and its numeric limits.

Generator execution belongs to the separate `engelfo` crate. Enge uses Rust uFor
for supported generator, Patch, binding and modulation preparation, and resolves
configured MIDI tunings to Hz before rendering. See
[enge's integration record](https://github.com/rec/enge/blob/main/doc/rust-ufor-integration.md).
Rust decodes processor and SoundSettings bodies. Full instrument and effect
documents and resource resolution are separate milestones.

The crate uses Rust 2024 with a minimum compiler version of 1.85. Import symbols
from their defining modules:

```rust
use ufor::expression::evaluate;
use ufor::number::Rational;

let value = evaluate("5/4")?;
assert_eq!(value.rational(), Some(Rational::new(5, 4)?));
let step = evaluate("2^(1/12)")?;
assert!(step.rational().is_none());
# Ok::<(), ufor::error::Error>(())
```

`Number` distinguishes exact `Rational` values from approximate finite `f64`
values. Rational components are reduced signed 64-bit integers with positive
denominators. Arithmetic cross-cancels where possible, checks overflow, and
returns `Error::ArithmeticRange` rather than silently converting an exact result
to float. Fractional powers produce approximate values even when their numerical
result is an integer. `Rational::from_f64` recovers the exact binary fraction only
when its components fit the same bounds.

The expression parser accepts decimal/scientific literals, parentheses, unary
signs, division, and `^` powers. It implements the documented grammar directly,
including leading zeroes and whitespace between tokens. Limits are 4096
characters, 64 levels of parentheses or syntax depth, and exponent magnitude
1024 for powers. Scientific exponents have a separate magnitude limit of 4096;
exact literal construction and intermediate arithmetic must still fit 64 bits.
Signed and zero expressions are permitted; `Number::positive` supplies the
additional pitch constraint.

`limit_denominator` approximates the exact input, including the binary fraction
of an approximate value. Ties favor the smaller denominator, then the lower
value when the denominators also tie. Numeric display uses Rust's formatting
and is not a canonical cross-language serialization of approximate values.

Validated constructors and Serde deserialization reject the same invalid
definitions. Source fields and evaluated tables are private and immutable;
construct a new value to edit a definition. Methods return typed `Error` values
for domain, arithmetic, positivity, or work-limit failures.

```rust
use ufor::codec::{self, Format};
use ufor::tuning::{Computed, Source, Tuning};

let tuning = Tuning::new(Source::Computed(Computed::default()), 69, "440Hz".into(), 0.0)?;
assert_eq!(tuning.evaluate(81)?.to_string(), "880");
let text = codec::tuning_text(&tuning, Format::Toml)?;
assert_eq!(codec::parse_tuning(&text, Format::Toml)?, tuning);
# Ok::<(), ufor::error::Error>(())
```

`codec::parse_tuning` and `tuning_text` handle tuning bodies.
`codec::parse_score(text, format, limits)` and `score_text` handle the typed
`score::Score` enum described in [Score coverage](#score-coverage). Select JSON
or TOML with `Format`. The score codec requires an explicit supported `kind`.
Deserializing a concrete score type can supply its default `kind`.
`PreparationLimits` controls record budgets for EnveLFO, sequence, automation,
and performance binding scores. Tuning has fixed table and materialization
bounds. Direct Serde use also validates models. The codec additionally enforces
the Python codec's 16,777,216-character, 100,000-value, and 64-level document
budgets.

`codec::parse_value` applies those same document budgets to generic JSON/TOML
values, allowing consumers to decode preparation declarations with existing uFor
types. It does not establish domain validity or retain object declaration order.
Order-sensitive generator/score bodies must still use their typed adapters on
the original text. This helper does not add a full instrument/settings model.

Tables may have at most 10,000 entries. The same limit applies to materializing
`Computed::as_ratios()`, while the stored computed note count may be any positive
`i64`. Finite sources reject notes outside their domain. Repeating sources use
Euclidean division for negative degrees. Detuning must produce a positive finite
frequency; underflow, overflow and approximation to zero are explicit errors.

The portable frequency units are `Hz`/`hertz`, `kHz`/`kilohertz`,
`mHz`/`millihertz`, and `MHz`/`megahertz`. Detuning supports
`cent`/`cents`/`musical_cent`, `semitone`, and `octave`/`oct`.
Unit spellings are case-sensitive. A quantity may use one unit factor attached
to a numeric power/sign term or parenthesized expression, or a bare unit meaning one unit.
For example, `1 kHz / 3` and `(440/3) Hz` normalize to exact hertz expressions;
`2^3 kHz` means 8,000 Hz. Use parentheses for powers of an entire quantity.
Division and powers must leave the expected dimension: `1/(3 kHz)` and `1Hz^2`
are rejected. Multiple unit factors and general Pint syntax are outside this
adapter. Unitless frequency strings retain their spelling.

Python installation remains independent of Rust. The core uses Serde,
`serde_json` and `toml` for document interchange and `sha2` for deterministic
sample draws,
without Python or host-library dependencies.

Run the native checks from the repository root:

```sh
cargo test --workspace --locked
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
```

The release workflow runs these checks on Linux, Windows, and macOS with the
minimum compiler and current stable Rust. A local macOS result does not establish
that those hosted jobs have passed.

Python and Rust pass the same shared definition, expression, preparation, unit
and document cases. Python uses `model_validate` or `model_validate_json` with
`context={'portable': True}` for strict portable input; the score codec applies
that context automatically. Ordinary Python construction retains authoring
coercions and broader Pint syntax. Both languages enforce checked pitch
arithmetic and preparation limits during evaluation. No tuning expected failures
remain. Hosted platform qualification is still tracked in [the plan](../plan/rust-tuning.md).
