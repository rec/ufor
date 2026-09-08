# Instrument contract and the next cutover

This document fixes the boundary for the small sample-instrument profile.
The shared performance events and [modulation routes](#modulation-routes) below
are implemented. The native instrument document, prepared voice settings,
selection/gate state machine, and SFZ cutover are the next coordinated change.
Their field inventory below is a specification for that change, not a claim
that `parse_document` already accepts `kind = "instrument"`.

There is no sampler, waveform renderer, voice scheduler, or plugin host in
this milestone. Existing Recsam instrument files still use their existing
native root. Their event classes are replaced with the shared Ufor classes;
no compatibility event module or frame-to-tick fallback is retained.

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
field and its implicit list-order tie breaking. Other Recsam declarations are
not cut over merely because their event types have moved.

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
`volts`, and `seconds`. Hertz domains are strictly positive; duration domains
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
is duplicated in a route. The eventual instrument validator must verify that
source scope and domain match the bound generator/control declaration.

## Native instrument structure to implement next

Use the common root `kind = "instrument"` with a body identifying the
`sample_instrument` profile. The root owns document identity/name, native
timebases, sealed assets, dependencies, and exported performance/audio ports.
The body owns instrument settings, named slices, slots, source bindings,
modulation, selection sets, and voice limits. These are one native root;
Recsam's old `format_version` root is removed at the cutover.

| Structure | Contract |
| --- | --- |
| Sample asset | Common `Asset` identity/path/hash/size plus `AudioDescription` with native timebase, frames, and channel names |
| Slice | Stable ID, asset ID, and one half-open native-frame range contained in that asset |
| Slot | Stable ID, slice ID, selection/mapping declarations, explicit named output, effective playback and sound settings |
| Loop | Existing traversal mode and crossfade semantics; absolute native asset-frame coordinates contained in the slice |
| Performance input | Named port accepting the event family above; input timebase is resolved explicitly at preparation |
| Audio output | Named port with explicit channel layout and execution timebase; no private bus or filename inference |
| Modulation | The typed collection above, with each source bound to a declared control, key/velocity input, envelope, or LFO |
| Voice limits | Separate positive trigger and voice capacities, plus an explicit retirement fade duration |

The asset and output timebases are separate. A 44.1 kHz sample remains in its
native frame coordinates in a 48 kHz instrument execution context. Pitch and
resampling affect traversal, not the meaning of its slice or loop bounds.
Unpitched slots require no invented reference frequency. Pitched slots retain
an independent reference pitch and require a resolved performance pitch.
Channel selection and output mapping must be explicit before execution;
multichannel samples are not silently interpreted as stereo.

## Preparation and inheritance

Preparation produces complete immutable voice settings from authoring
declarations. Preserve the existing additive dB/cents processing and local
control/reference rules. Omitted slot playback settings inherit; explicitly
supplied defaults override. Resolve the old per-field DAHDSR inheritance before
expanding an envelope to Ufor segments. The new native format stores a complete
envelope override, not a partially merged segment list. Named source IDs are
local to the declaring voice/instrument context and must not accidentally
resolve into another slot.

Keep selection, sustain, choke groups, articulations, crossfades, and EQ as
typed musical concepts. Use the existing validators where their semantics
still apply. Move pure types to Ufor and import them directly from there.
Filesystem resolution, symlink containment, decoding, hashing, units authoring,
and SFZ file access remain in Recs. An unresolved asset must not receive a
fabricated length, checksum, sample rate, or channel layout.

## Performance and voice state decisions

These state-machine rules retain the useful existing instrument semantics.
The implementation and portable action traces are part of the upcoming
cutover, not part of the scalar route evaluator:

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

## Coordinated cutover checklist

1. Implement the native root, asset slices, source bindings, resolved settings,
   and validators together with portable event-to-action traces.
2. Replace the old Recsam model definitions and every direct consumer; keep
   file I/O and SFZ parsing/writing in Recs. Do not create forwarding modules.
3. Make SFZ import construct real common asset metadata and slices; make export
   resolve slice paths/bounds and report every unsupported envelope, route,
   scope, selection, or lifecycle feature. Never report a lossy export complete.
4. Replace native examples and tests, including inheritance and SFZ regression
   fixtures. Keep historical production recordings and audio payloads untouched.
5. Update Recs's public Ufor archive pin in its own dependency commit before
   consumer code begins importing the new native instrument types.

No backwards-compatibility reader is required. The current milestone already
updates the Recs dependency for shared events; the later root cutover will pin
the revision that actually contains those new types. New audio generation,
sampler implementation, compiled-language selection, and VST realization remain
behind the separate execution decision.

## Additional work beyond the prompt

None.
