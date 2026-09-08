# Sample instrument format

The native `instrument` document, sample models, source bindings, and pure SFZ
conversion are implemented in Ufor. `ufor.codec` reads and writes this profile
alongside recordings, sequences, arrangements, tunings, scales, oscillators,
envelopes, and LFOs. The defining modules are `ufor.samples.*` and `ufor.sfz`.
Recs owns file access and asset inspection; it no longer owns parallel models.

This is a format and scalar-control implementation. Prepared voice settings,
selection/gate/retirement state machines, and audio generation remain future
work. There is no sampler, waveform renderer, scheduler, or plugin host.

## Performance input

The defining module is `ufor.events`. `Trigger`, `Release`, and `ControlChange`
extend the same native `Event` envelope as captured MIDI, OSC, and keys. They
belong to both `PerformanceEvent` and `StoredEvent`. Common sequence documents
and native JSONL parsing can therefore carry semantic performance events.
Recording event-kind filters also recognize their three kind names. Existing
capture adapters do not infer musical triggers from incoming raw MIDI.

Every event has a strict integer `tick` and nonnegative strict integer
`ordinal`. Its containing sequence or event stream names the physical
timebase. A 48 kHz timebase gives audio-frame coordinates, while another
timebase may give nanoseconds. Negative ticks permit preroll within the
declared sequence extent. Preserve native ticks; do not convert each event
through a floating-point number of seconds. Sequence ordinals are unique
throughout the sequence, and events are ordered by `(tick, ordinal)`.
The [portable sequence](../conformance/performance.json) exercises preroll,
same-time onsets, independent pitch, and release by identity through both
the common TOML codec and native event JSON.

| Kind | Payload | Meaning |
| --- | --- | --- |
| `trigger` | `part`, `trigger_id`, integer `key`, `velocity`, optional positive `pitch_hz`, `controls` | Start one independently identified performance onset |
| `release` | `part`, `trigger_id` | Physically release that onset, not whichever voice happens to share its key |
| `control_change` | `control`, normalized `value`, `scope`, optional addressed part/trigger | Change the explicitly addressed control context |

Keys are unrestricted integers and select sample regions independently of
pitch. `pitch_hz` is already resolved Hz, not a MIDI note number. Tunings remain
separate definitions used by the caller to resolve it. Zero velocity remains
a trigger. Velocity lies in [0,1]; event controls lie in [-1,1] and undergo
the instrument's declared polarity/domain check. Trigger IDs cannot be reused
within a part while held or still owning live voices, preserving Recsam's rule.
The eventual performance state machine, rather than a generic sequence
parser, enforces that lifetime rule and requires pitch when a selected slot
tracks pitch.

Part, trigger, and control IDs use Ufor's common identifier rule: a lowercase
letter followed by lowercase letters, digits, hyphens, or underscores.
Instrument control declarations must use that same domain so every declared
control can be addressed by an event.

Control scope is `instrument`, `part`, or `trigger`. Instrument controls have
neither part nor trigger ID. Part controls require only part; trigger controls
require both. A trigger's initial control map initializes only its trigger
context. The instrument declares which controls exist and their defaults.
There is no MIDI channel or CC number in these events; those belong to a
transport binding.

An audio or envelope adapter converts a native tick exactly as
`tick * timebase.rate.denominator / timebase.rate.numerator`. It forwards
logical gate events at that rational coordinate while retaining ordering.
Physical release is not automatically logical gate release when sustain is
active. These Ufor event classes replace Recsam's former nonnegative `frame`
field and its implicit list-order tie breaking. The remaining Recsam declarations now use the native document below.

## Modulation routes

`ufor.modulation.Modulation` is an embedded collection of typed `parameters`,
`sources`, and `routes`. It is a fragment for instrument/processor bodies,
not another native document root. Its schema is
[schema/modulation.json](../schema/modulation.json); its numerical cases are
[conformance/routes.json](../conformance/routes.json).

| Model | Fields and ownership |
| --- | --- |
| `Target` | Structured `{node, parameter}` identity; neither field is a dotted path |
| `Parameter` | Target, unit, voice/instrument scope, finite minimum/maximum, and in-domain default |
| `Source` | Local source ID, instrument/part/trigger/voice scope, and finite input domain |
| `Route` | Stable ID, source ID, target, add/multiply operation, output unit, ordered mapping points, interpolation |
| `SourceValue` | One instance's observed value and activation weight in [0,1] |
| `ParameterValue` | One addressed parameter and its scalar value |

Supported parameter units are `ratio`, `db`, `cents`, `hz`, `normalized`,
`volts`, `seconds`, and `beats`. Hertz domains are strictly positive; duration domains
are nonnegative; normalized domains are within [-1,1]. Other numeric bounds
are explicit declarations. Addition must use the target's unit. Multiplication
must use `ratio`; a cents or dB conversion must already have been made by an
explicit mapping producer. No unit is guessed from a parameter name.

Mapping points have `input` and `amount`; inputs increase strictly and lie
inside the source domain. A single point is constant. Outside the knot range,
mapping holds the first/last amount, but the source value must still be inside
its declared domain. `linear` interpolates between adjacent knots; `step`
changes exactly at the next knot. Unknown IDs, duplicate source/route/target
identities, incompatible units, or ambiguous references are rejected.

Each evaluation handles one resolved instance context. A voice parameter may
consume its own voice source or its parent trigger, part, or instrument source.
An instrument parameter accepts only instrument sources. Aggregating voices
or parts requires a separate explicit operation; a shared parameter never
inherits whichever voice happened to run last. The host binds source IDs to
the correct context before calling the evaluator. Scope metadata cannot prove
that the caller supplied the right physical controller or parent instance.

`evaluate` takes that collection, observations by source ID, and optional
replacement base values. It requires every routed source, rejects unknown
sources, and permits at most one base override for each declared parameter.
The definition is immutable and is not changed by an override. The result
contains one value per declared parameter in parameter-declaration order.

For each route, map the source value first. With activation weight w, additive
amount a contributes `w*a`; multiplier m contributes `1+w*(m-1)`. Then compute
`(base + sum(additive contributions)) * product(multiplicative contributions)`.
Routes are reduced in `(source ID, route ID)` order; reordering their declarations
does not alter meaning. The reference uses accurately summed additive terms;
portable numerical comparisons use absolute tolerance 1e-12 for the supplied
cases. Base and final values must remain in the parameter domain. There is
no implicit clipping or missing-source default.

The evaluator does not assume independent sources and reject declarations
using conservative combinations that may never occur. It checks the actual
resolved result. A preparation-time range proof can be added by an instrument
host, but cannot substitute silent clipping for a failed runtime domain check.

Envelope and LFO definitions remain the only definitions of their generated
control behavior. Source observations consume their scalar values; an LFO's
activation weight is forwarded separately. No oscillator or envelope engine
is duplicated in a route. The instrument validator verifies that source scope and domain match the bound
generator/control declaration. The sample profile also preserves conservative
combined pan/balance bounds; the generic evaluator still checks actual results.

## Native instrument document

`InstrumentDocument` uses the common header and `kind = "instrument"`.
`body.kind = "sample_instrument"` identifies the specialized musical body.
There is one native format; the old `format_version` document is removed.

| Owner | Fields |
| --- | --- |
| Root | `id`, `name`, optional `description`, `tags`, native `timebases`, sealed `assets`, `performance_port`, `audio_port`, typed `output`, `body` |
| Body | `instrument` defaults, named `slices`, nonempty `slots` |
| Audio asset | Common ID/path/encoding/byte length/SHA-256 plus `audio` description with native timebase, frames, and channel names |
| Slice | ID, asset ID, nonnegative `start_frame`, required exclusive `end_frame`, optional loop |
| Slot | ID, slice ID, mapping, explicit channel routes, playback overrides, sound settings, selection/choke/articulation/crossfade declarations, trigger kind, metadata |

All references are checked without opening files. Slices must be nonempty and
contained in the asset; loops remain in absolute native asset-frame coordinates
within the slice. Asset paths cannot be absolute, URLs, or contain `..`.
The application checks symlinks, hashes, actual decoding, and file availability.

This complete example uses synthetic asset metadata for illustration. Its zero
hash is not a claim about an existing file. Real documents require measured
asset facts, as supplied by Recs' importer.

```toml
format = "recs"
version = 1
kind = "instrument"
id = "glass"
name = "Glass"

[[timebases]]
id = "native"
rate = { numerator = 44100 }

[[timebases]]
id = "output"
rate = { numerator = 48000 }

[[assets]]
id = "glass"
path = "audio/glass.wav"
encoding = "WAV/PCM_16"
byte_length = 88244
sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
audio = { timebase = "native", channels = ["mono"], frames = 44100 }

[output]
timebase = "output"
channels = ["left", "right"]

[body]
kind = "sample_instrument"

[body.instrument]

[[body.slices]]
id = "whole"
asset = "glass"
end_frame = 44100

[[body.slots]]
id = "middle"
slice = "whole"
channels = [
    { input = "mono", output = "left", gain = 0.7071067811865476 },
    { input = "mono", output = "right", gain = 0.7071067811865476 },
]
mapping = { lowest_key = 48, highest_key = 84, reference_pitch_hz = 440.0 }
```

The [SFZ input](../conformance/instrument.sfz) and
[complete native result](../conformance/instrument.json) form a portable
conversion case with explicit synthetic metadata. They cover 44.1/48 kHz
separation, exact envelope times, slice endpoints, and velocity mapping without
loading or generating audio. JSON Schema lives in
[documents.json](../schema/documents.json).

## Musical settings and inheritance

`ufor.samples.playback` owns mappings, traversal, slices, and loops.
`controls`, `selection`, `crossfade`, and `processing` own the other specialized
musical declarations. These use Ufor's common frozen model and identifier rule.
There are no Reccy or application units in the format. Hz and other scalar
magnitudes are numeric; envelope/LFO time and phase use exact rational strings.
Frequency/ratio expression authoring remains in the musical definitions.

`SlotPlayback.direction` and `.mode` are nullable overrides. Null/omitted values
inherit; an explicit default overrides, even after full JSON/TOML serialization.
A slot's amplitude `envelope` is either absent or one complete shared
`ufor.envelope.Envelope`; it never merges individual stages. The instrument
supplies a default instantaneous gate. Amplitude envelopes are unipolar and
voice-scoped. Named `envelopes` and `lfos` are dictionaries keyed by local IDs,
using the same definitions as standalone envelope and LFO documents.

Key and velocity ranges are inclusive. Keys are unrestricted integers, independent
of pitch. Pitch tracking requires `reference_pitch_hz`; the eventual player also
requires a resolved trigger pitch. Unpitched mappings need no invented pitch.
The pitch ratio is target/reference times `2 ** (combined_cents / 1200)`;
resampling additionally uses native/output rate. It changes traversal speed,
not the asset's native frame coordinates, and is not time stretching.

Forward traversal reads first to last; backward reads last to first; mirror
reads first to last and back once without doubling the turning endpoint.
For A B C D this is A B C D C B A. Loops require at least two frames and
`while_held` playback. Loop crossfade is either zero or at least two frames
and shorter than half the loop. Mirror loops cannot crossfade. `until_release`
leaves the loop when the logical gate opens; `through_release` continues it
through the amplitude release. Detailed audio traversal conformance belongs to
the deferred execution work, not to the scalar envelope evaluator.

Selection sets retain cycle/random/shuffle declarations; slots reference them.
Matching ordinary layers coexist with selected alternatives. Random/shuffle
execution needs a named algorithm and seed before portable playback can be
claimed. Choke groups retain immediate/fade/release modes; fade alone requires
a positive fade time. Choking is distinct from physical or logical release.
Release and sustain-transition slots require one-shot playback. Sustain slots
require the declared unipolar sustain control, an untracked mapping containing
`event_key`, and consistent event keys across alternate takes.

Articulation IDs and references are unique and checked. Keyswitches are latched
or momentary and may consume their trigger. Control selectors use disjoint
inclusive ranges inside the declared control domain. The intended player keeps
selection per part, captures articulation for each onset, and matches momentary
release by trigger identity. These are declarations and future state-machine
requirements, not an implemented voice engine.

Layer crossfades remain separate from modulation routes. Key/velocity transitions
must fit inside the slot's eligibility range; control fades use declared control
domains. Clamp normalized transition position to [0,1]. Linear fade-in/out uses
`t` / `1-t`; equal-power uses `sin(pi*t/2)` / `cos(pi*t/2)`. Multiply weights
within a slot without normalizing across layers. Zero weight does not suppress
selection or voice ownership. Static fades are latched at onset; live fades
smooth position before applying the gain law so complementary pairs remain
complementary. Execution and smoothing traces remain deferred.

## Source bindings and parameter addresses

Each entry of `modulation.sources` has exactly one `bindings` entry with the
same ID. Bindings have tagged forms:

| Kind | Binding fields | Source contract |
| --- | --- | --- |
| `key` | `id`, `kind` | Voice scope; integer bounds covering selected keys and integer mapping knots |
| `velocity` | `id`, `kind` | Voice scope and [0,1] domain |
| `control` | `id`, `kind`, `control`, exact seconds `smoothing` (default `1/200`) | Declared polarity domain; instrument/part/trigger scope |
| `envelope` / `lfo` | `id`, `kind`, `reference` | Existing local named generator; exact scope and polarity domain match |

A source ID never resolves into another slot. Instrument-scoped generators may
be shared by voices through explicit bindings; slot generators are voice-only.
LFO activation weight remains separate from its scalar signal. There is no
second sample-specific envelope, LFO, waveform, or route implementation.

Structured target nodes and parameters are:

| Node | Parameter | Unit |
| --- | --- | --- |
| `processing` | `amplitude` | ratio, base 1 |
| `processing` | `volume_db`, `tuning_cents`, `pan`, `stereo_balance` | db, cents, normalized, normalized |
| `eq-ID` | `frequency_hz`, `gain_db`, `resonance` | hz, db, ratio |
| `envelope` or `env-ID` | `on-N-duration`, `release-N-duration` | seconds or beats from the envelope clock |

N is a zero-based segment index. The declaration's unit and default must match
the actual bound setting. Envelope parameter scope matches its generator;
duration inputs are latched from key or velocity. Arbitrary recursive generator
modulation is not introduced. Generic routes retain explicit finite domains,
add/multiply operations, mapping knots, and runtime result checks.

## Processing and channels

Instrument and slot processing both run per voice, before mixing. Instrument
settings affect every voice; they are not a single post-mix effect. Their
volume and tuning add in dB/cents. Slot EQ bands precede instrument EQ bands,
with IDs local to each scope. EQ means bell-shaped peaking biquads with positive
Hz/Q, not arbitrary filters. The eventual prepared player must check effective
frequency against output Nyquist and retain independent filter state per voice.
A shared post-mix effect belongs to a separate processor graph.

Channel routes explicitly name input/output channels and linear gains. There is
no implicit stereo interpretation or downmix. Standard mono-to-stereo mapping
has `sqrt(1/2)` gain to each side; stereo identity has unity corresponding gains.
Custom matrices are allowed when spatial controls are unused.

`pan` requires mono input and stereo output; `stereo_balance` requires stereo
input/output. Both require their canonical channel map. Instrument and slot
values, including routes, combine into one spatial operation. Pan varies the
canonical map to `cos(pi*(p+1)/4)` / `sin(pi*(p+1)/4)`; it does not apply a second
center attenuation. Balance attenuates the opposite channel by
`cos(pi*abs(b)/2)` and leaves the other channel unchanged. It never folds channels
together. Combined ranges must stay within [-1,1], including neutral amounts
during delayed/fading LFO activation. No clipping or automatic normalization is
part of the instrument format.

## SFZ and application ownership

`ufor.sfz.parse(text)` produces parsed regions and diagnostics.
`sample_paths(source)` lists safe relative sample references.
`compile(source, id=..., name=..., assets=..., output_timebase=...,
output_channels=...)` accepts `ufor.samples.metadata.AudioMetadata` facts
supplied by the caller and produces an `InstrumentDocument` where possible.
All of these operations are pure. Unsupported opcodes retain source locations;
missing or malformed required data fails explicitly.

SFZ's fixed DAHDSR becomes four on-segments and a release segment. Delay/attack/
hold curves are 0; decay/release are -5. SFZ decimal durations become exact
fractions. Export accepts that representable shape and reports general envelopes
as unsupported. Velocity response becomes the shared typed multiplier route.
SFZ inclusive endpoints become exclusive native slice/loop ends and reverse on
export. Imported channel maps are identity or the standard mono-to-stereo law.

`ufor.sfz.write(document)` returns text and diagnostics without opening files.
Unsafe sample syntax, custom channel maps, named controls/generators, selections,
nonrepresentable routes/envelopes and other losses are reported. Diagnostics
use native `body.slots[...]` / `body.instrument...` paths. A partial export must
not be treated as complete. Recs' metadata comment namespace remains understood.

`recs.recsam.sfz.read(path)` is the application adapter. It checks resolved path
containment, reads/decodes metadata, inspects embedded WAV loops, hashes the
existing file, and passes those facts to Ufor. Its explicit application default
is 48 kHz stereo output; callers may select another supported output layout/rate.
It does not generate audio. `recs/recsam/` now contains only this adapter and
asset I/O, plus an empty package marker.

## Updating old declarations

There is no compatibility reader. Replace `format_version` with the common
header and put the musical settings under `body`. Move name/description/tags
to the root. Seal sample paths as assets, move trim/loop data to named slices,
point slots at those IDs, and declare channel maps/output clocks explicitly.

Resolve old partial DAHDSR overrides once and expand complete envelopes into
segments. For old exponential attack use +5; exponential decay/release use -5.
Replace LFO Hz/delay/phase fields with rate/delay/phase in the shared clock model.
Phase now advances during delay; an intentional preservation of old activation
phase uses `(old_phase - rate * delay) mod 1`.

Replace old Key/Control/GeneratedModulation objects with the one shared source,
binding, parameter, and route collection. Replace dotted target strings with the
addresses above. Translate authoring unit strings to canonical numeric magnitudes
or exact rational time strings before constructing models. Preserve selection,
choke, articulation, crossfade and mapping concepts using their Ufor classes.
Import directly from defining modules; old Recsam modules have been removed.

The detailed [performance requirements](sample-performance.md) retain the
selection-state partitioning, choke ordering, articulation ownership, and loop
overlap/release rules from Recsam for the future player.

## Preparation boundary

Preparing efficient lookups, resolving effective voice settings, defining voice
limits, enforcing trigger lifetimes, and producing event-to-action traces remain
future work. Dependencies on other instrument documents, multiple audio output
ports, linked microphones, and generic graphs need their own settled models.
This extraction does not add speculative fields for those unimplemented features.

## Performance and voice state decisions

These state-machine rules retain the useful existing instrument semantics.
Their implementation and portable action traces remain a later preparation
milestone, separate from this completed format extraction:

| Input/cause | Required behavior |
| --- | --- |
| Trigger | Resolve articulation/selection once for that trigger, then create all selected layers; overlapping equal-key triggers remain independent |
| Physical release | Mark the identified trigger physically released; fire eligible physical-release samples once |
| Sustain held | Defer ordinary logical gate release while the part's sustain control is above its declared threshold |
| Sustain falling below threshold | Release deferred logical gates in original trigger order and fire eligible logical-release samples once |
| Repeated or unknown release | No extra release samples or restarted envelope |
| Choke/steal/transport stop | Use that distinct retirement cause; do not fabricate a physical release or fire its samples |
| One-shot or release/sustain sample | Ordinary physical release does not truncate it; explicit retirement still applies |
| Envelope completion | Retire only when the voice contract assigns that envelope the amplitude-lifetime role |

Process equal-time inputs in ordinal order, including controls, keyswitches,
trigger creation, and releases. Do not batch by event kind. A pedal change
before release at one tick can change whether that release is deferred.
Legato is a host performance policy that may omit a trigger; it is not inferred
by an envelope from another key's activity. Pitch changes do not mutate a
trigger's selection key or select another sample retrospectively.

Enforce capacities deterministically: eligible released voices first, then
oldest trigger, then stable IDs to break ties. A trigger limit retires the
whole selected onset, including its layers; a voice limit must have explicit
layer-retirement behavior in the action traces. Applying either retirement
uses the declared fade and does not depend on block size.

Cycle selection counters belong to named sets and reset at performance start.
The first prepared profile supports deterministic cycle selection. Existing
random/shuffle declarations need a named algorithm, seed, and portable cases
before they can be prepared; they must not be silently converted to cycle.
Linked microphone take groups remain a later extension requiring one shared
take-selection identity, rather than independent random selection per mic.

## Additional work beyond the prompt

None.
