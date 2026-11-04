# Sample performance requirements

These musical behavior requirements were retained from the Recsam specification
when its types moved to Ufor. The [native instrument format](instrument-format.md)
defines the implemented data. This appendix records the intended future player
behavior, not implemented scheduling or audio processing. Semantic traces now
cover selection, chokes, physical and logical release, and sustain transitions;
seeded parameter variation is also resolved during preparation. Rendering
remains host work.
Any conflict with the new shared envelope/LFO model is resolved in favor of
[that model](modulation-format.md): exact cumulative times, whole envelope
overrides, and separate completion/lifetime policy.

Instrument and slot processing remain per voice, before mixing. Phase during
LFO delay follows the shared model. Native events use tick/ordinal ordering;
references below to equal-frame input order mean that explicit ordering.
Random and shuffle selection use the portable state contract below. It is pure
preparation logic, not audio rendering or voice scheduling.

## Semantic trace

`ufor.samples.trace.SampleTrace` records reference lifecycle decisions against
the original instrument definition. Consumers require both the trace and that
definition. It records the explicit performance seed, actions ordered by
`(tick, ordinal)`, and optional observational snapshots. Snapshots describe the
preparer's logical voices and triggers, not complete restorable player state:
Sample snapshots retain selection controls and articulation state, but omit
complete smoothed control trajectories, sustain state, and renderer completion state.
Seeking currently requires replay from the beginning; no snapshot-resume API is
provided. SelectionState alone remains serializable and usable by `choose`.

`voice_start` records a stable voice ID, part and optional trigger ID, chosen slot and
slice, resolved native start and alignment frames, channel routes, and effective
slot/group sound settings. Instrument-level settings, mapping, playback, loops,
and crossfades remain in the original definition. The current preparer does not
evaluate modulation into `parameters`; consumers must not interpret its empty
list as a resolved set of controls. Synth actions serialize the full `SynthVoice`
settings, including synchronization and minimum hold time. `voice_retirement` names the
voice, its distinct cause (physical/logical release, choke, same-key policy,
voice limit, or transport stop), and whether the voice releases or stops.
Fade retirements use `action = "fade"` with positive `fade_seconds`. Chokes
affect only existing voices on the event's part. Simultaneous immediate chokes
win over other modes, and simultaneous fades use the shortest duration. The
current preparer rejects a combined fade and envelope-release choke on one
voice because a single retirement cannot express their combined gain curve.
`trigger_context` precedes each accepted onset's voice actions and preserves its
velocity and complete initial control values, even when it selects no voice.
The sample preparer emits `trigger_release` once for the first physical release
of a known trigger, carrying its part and trigger ID. It precedes voice actions
created by that release, including release-triggered starts. It is emitted for
one-shot voices and while sustain defers logical release, independently of voice
retirement. Consumers use it to cancel pending start-triggered voices; it does
not release or stop already-playing one-shot or sustained voices. Unknown
releases remain diagnostics, and repeated releases emit no second observation.
`control` preserves an addressed control observation, including changes while
silent and during release. Context lifetime, smoothing, and pitch composition
are specified in [instrument control evolution](control-evolution.md).
`diagnostic` records a
recoverable preparation failure without inventing a voice.

The trace deliberately excludes audio blocks, interpolation positions, filter
delay elements, oscillator phase buffers, and generated audio. Those remain
renderer choices. The sample preparer supports latched key articulations and
rejects momentary and control-driven articulations. A trace is not proof that a renderer supports
every feature in its definition.

Input events are processed in increasing `(tick, ordinal)` order; duplicate
coordinates are rejected. Snapshots use the final processed coordinate. Voice IDs
are trace-local `voice-N` identifiers numbered from zero in start-action order,
independent of punctuation in part/template/trigger names. A trigger ID cannot be
reused until logically released and no longer owning a logical voice in the trace.
The current preparer receives no audio-exhaustion feedback, so one-shot and release
voices remain logically active unless explicitly retired.

## Note and control selection conditions

Each slot's `key_conditions` requires every named key to be physically pressed
or released in the event's part. `SelectionState.held_keys` maps each part's
still-pressed trigger IDs to keys, so overlapping presses remain held until all
matching releases arrive. A press is recorded before note-on selection and a
release before release selection. Sustain does not retain physical presses.
Conditions combine with articulation and control conditions; they select new
voices without changing voices already playing. An articulation declaration may
have an empty `ids` list and consumed keys with no articulation, allowing switch
notes to be consumed independently of sticky selection.

A slot's optional `previous_key` requires the preceding note-on key in its part.
`SelectionState.previous_keys` starts empty, is checked before recording the
current note-on, and includes consumed switches and unmatched note-ons. History
survives releases and silence. Native release conditions consult current history;
source formats must diagnose release-history rules without a verified equivalent.

A slot with `trigger="control"` requires `control_trigger`: a declared named
control, inclusive range, explicit `pitch_hz`, and explicit `velocity`. It starts
on every matching part-scoped `ControlChange`, including repeated values. The
control value is updated before selection. Instrument- and trigger-scoped changes
do not start these voices. Defaults do not generate events. Ordinary control,
key, and articulation conditions evaluate the current part state.

Control voices require one-shot playback and have no note key or trigger ID;
their `voice_start` records `key=null`, `trigger_id=null`, and the authored pitch
and velocity. Existing chokes and voice limits apply, while same-key rules do
not. They do not update previous keys, physical presses, or note-on counters, and
note releases, sustain, or leaving the controller range do not release them.
Sequence positions, random ranges, alternate selections, and crossfades are
outside this first control-trigger model. The reference preparer still has no
audio-completion feedback: the consumer finishes one-shots naturally, while the
trace retains their logical voices until an explicit choke or voice limit.

The portable [note-condition vectors](../conformance/note-conditions.json) and
[control-trigger vectors](../conformance/control-triggers.json) define the exact
selection, overlap, part isolation, and retirement results.

## Alternate Sample Selection

Declare named selection sets on the instrument and associate each alternative slot
with one set. A selection set is not a shared processing group.

Set IDs are unique. Each requires `mode = "cycle"`, `"random"`, or `"shuffle"`;
there is no implicit choice. A slot may reference only one existing set. Slots
without `selection` continue to layer normally.

First evaluate mapping conditions. Partition eligible slots by selection set,
then choose exactly one eligible slot from each nonempty set. Empty sets make
no choice and do not advance state. Filter before selecting: differing velocity
layers or key ranges must not create silent holes in a sequence. Zero gain is
not a mapping exclusion.

- `cycle`: visit eligible slot IDs in ascending Unicode code-point order, wrapping at the
  end. The initial choice is the first ID.
- `random`: choose uniformly among eligible slots on every trigger; immediate
  repetitions are allowed.
- `shuffle`: choose a uniform random permutation, consume it once, then refill.
  With at least two candidates, refills are uniformly chosen from permutations
  whose first slot differs from the previous choice. A single candidate always
  plays.

State is independent per set, part, trigger kind, trigger key, and
ordered tuple of eligible slot IDs. Velocity layers therefore have independent
sequences when their eligible IDs differ; changing velocity without changing
that tuple advances the same sequence. State advances once per selected set
per triggering event, not per audio block or active voice. Returning to a
previous eligible tuple resumes its state. Loading or explicitly resetting an
instrument clears all sequence state; ordinary release events do not reset it.

`SelectionState` begins with the explicit unsigned 64-bit performance `seed`.
It contains independent `SelectionSequence` values keyed by part, set ID,
trigger kind, trigger key, and ordered eligible slot IDs. The sequence records
its counter, the remaining shuffle bag, and the previous choice. A performance
start creates fresh state from its seed. SelectionState can be serialized and
supplied to subsequent selector calls. An instrument snapshot includes that state
for observation, but is not resumable; instrument seeking replays from the seed
and original event history. Controls, releases, inactive sets,
audio block boundaries, and unrelated state partitions do not advance a
sequence.

For `random`, derive the candidate index from SHA-256 using length-prefixed UTF-8
values: the decimal seed, part ID, set ID, trigger kind, decimal key, each sorted
candidate ID, decimal counter, empty excluded-candidate field, and decimal retry
number. Interpret the 32-byte digest as an unsigned big-endian integer and use
rejection sampling to reduce it into the candidate count. Increment the counter
once after each choice. This is the named `sha256-counter-v1` algorithm.

For `shuffle`, use the same indexed draws to form a Fisher-Yates permutation. On
a refill after a prior choice, choose the first item uniformly from candidates
other than that choice, then shuffle the remaining positions. Thus every allowed
permutation is equally likely and a refill never immediately repeats the prior
choice. Increment the counter once for every indexed draw. The state format and
these inputs are sufficient for independent implementations to reproduce every
choice exactly.

Future execution conformance must cover layering outside sets, several independent sets,
candidate filtering before selection, one/zero eligible candidates, shuffle
refill boundaries, and invariance under audio block-size changes.

## Note-On Position Conditions

`body.slots.sequence` is an optional `{length, position}` condition on a start
slot. Both values are positive integers and `position` cannot exceed `length`.
Each part has a note-on count, initially zero. Every accepted trigger event in
that part increments the count once, before slot mapping and selection, even
when its key or velocity matches no slot. A sequence slot is eligible when
`(count - 1) % length + 1 == position`. Other slots are unaffected. Multiple
slots at one position layer unless a separate named selection restricts them.
Release and control events do not increment the count. Counts are independent
between parts and appear in `SelectionState.note_on_counts` in snapshots.

This is the explicit `all_note_ons` counter rule. It is distinct from the
eligible-candidate counters of named selection sets and may produce silent
steps. Source-format conversion rules belong to safaz.

## Random Range Conditions

`body.slots.random_range` filters a slot after its trigger, key, velocity, and
sustain-event mapping match, and before named selection sets resolve. Its
`minimum` is inclusive and its `maximum` is exclusive. The interval must be
nonempty within `[0, 1]`; intervals may overlap to layer slots or leave gaps that
select none. This is separate from `Selection`: it never requires exactly one
slot to match.

For every input event, all candidate slots share one random value. Derive it with
SHA-256 from length-prefixed UTF-8 values: the domain tag
`sample-random-range-v1`, decimal seed, part ID, trigger ID (or empty), decimal
event tick, and decimal ordinal. Interpret the first seven digest bytes as an
unsigned integer and divide by `2 ** 56`, producing `[0, 1)`. This has no mutable
state, so unrelated voices, selections, and block boundaries cannot affect it.
`conformance/random-ranges.json` pins the portable case.

## Parameter Variation

`body.slots.variation` declares independent maximum variation for delay in
seconds, native sample offset in frames, pitch in cents, and gain in dB. Delay
and offset are drawn from `[0, maximum)` and `[0, maximum]` respectively; pitch
and gain are drawn from `[-maximum, maximum)`. Zero is the default for every
field and creates no variation.

The performance seed owns every draw. `sample-variation-v1` derives a SHA-256
digest from length-prefixed UTF-8 fields: the domain tag, decimal seed, part,
trigger ID (or empty), decimal event tick and ordinal, selected take ID or slot
ID, parameter name, and retry number for integer offsets. The top 53 digest
bits form floating draws in `[0, 1)`; offsets use rejection sampling across the
inclusive integer range. The resolved values are recorded on `voice_start`.

There is no mutable variation stream: a matching seed and event identity always
produces the same result regardless of block size, other voices, or prior draws.
The event coordinate distinguishes later reuse of a trigger ID. Linked microphone
slots use their shared take ID as the draw identity, keeping their random delay,
offset, pitch, and gain aligned. Sustain samples use their threshold-crossing
control event and slot ID. `conformance/variation.json` pins the first portable
case.

## Choke Groups

`body.slots.choke_group` labels voices created by that slot. Each `[[body.slots.chokes]]`
entry describes existing voices to stop when that slot is actually selected.

Choke groups are instrument-local IDs declared by membership, not processing groups
or selection sets. A slot belongs to at most one choke group and may choke
several groups. Every target must name a group used by at least one slot.
Membership alone does not cause mutual choking.

Each rule requires `group` and `mode`. Modes are `"immediate"` (stop before the
next output sample), `"fade"` (multiply the current output by a linear ramp
from one to zero), and `"release"` (enter the voice's release envelope).
`fade_seconds` is required, finite, and positive for fade; other modes
require it to be absent or null. Release also applies to one-shot voices when explicitly
choked; it follows the loop's release policy. Fades and immediate stops create
no sample tail beyond the voice's existing material.

After all slots for one event have been selected, take a snapshot of existing
voices on that event's part. Apply selected slots' choke rules to that
snapshot, then create all new voices. Voices created by the same event never
choke one another. Later events at the same frame are processed in event-stream
order and can choke voices from earlier events.

A selected closed-hat slot with a matching choke rule stops earlier open and closed hats, including older
instances of itself. Open-hat membership alone stops nothing. An unselected
alternate slot has no choke effect; a selected zero-gain slot still does.

Reject duplicate targets within one slot. If several selected slots target the
same voice, combine their termination gains by taking their minimum rather
than restarting or multiplying fades. An already-releasing envelope continues
from its current state; another choke never extends a voice's lifetime.
Choking is not a synthetic Release event and must not trigger release samples.

Future execution conformance must cover self-choking, layered event atomicity, part isolation,
unselected alternatives, already-releasing voices, and simultaneous rules.

## Layer Crossfades

Crossfades give overlapping layers complementary amplitude weights. They use
the same bounded curve evaluation as modulation, with a normalized position
instead of a separate arbitrary gain-automation language. These fragments go
in the respective existing slots.

Each entry requires `input` (key/velocity or a live input defined below),
`direction` (`"in"` or `"out"`), and `start < end` in that input's valid
range. Key coordinates are integers; velocity and control coordinates are floats.
`curve` is `"linear"` (default) or `"equal_power"`. A slot may have one entry per
`(input, scope, control, direction)`, allowing a fade-in and fade-out on each
axis. Static key/velocity inputs have no scope or control field.

Clamp `t = (input_value - start) / (end - start)` to `[0, 1]`. Linear weights
are `t` for fade-in and `1 - t` for fade-out. Equal-power weights are
`sin(pi * t / 2)` and `cos(pi * t / 2)` respectively, with exact zero and one
at the endpoints. The opposing slots must use the same interval and curve to
be complementary. Their mapping ranges must both include the entire fade
interval for key/velocity inputs; a reader rejects a slot whose mapping cuts
off its nonzero transition. Live inputs do not widen or constrain key/velocity
mappings.

Complementary layers need velocity mappings that overlap across the entire transition,
not just the shared endpoint in the complete instrument example. Crossfades neither widen mapping ranges nor
cause nonmatching slots to play. Matched slots with zero weight still create
voices and take part in selection and choking; silence is not a trigger filter.

Multiply all weights within a slot, then apply the result as a separate layer
gain alongside its envelope and volume before its EQ. Exact zero is silence,
not a fabricated finite dB value. Existing instrument and slot volume curves still
apply; neither replaces the crossfade. Key/velocity weights are captured at
trigger time; live-input weights use the source smoothing rules in
[instrument control evolution](control-evolution.md) before the fade law.

Pairing is explicit through matching parameters, not inferred from neighboring
slots. With three or more overlapping layers, all their weighted signals sum
without normalization. Equal-power weights preserve the sum of squared gains
for a complementary pair, not constant peak level for correlated recordings.
Authors remain responsible for headroom.

Future execution conformance must cover exact endpoints, midpoint gain laws, simultaneous key
and velocity fades, zero-weight voices, clipped mapping ranges, and three-layer
overlaps. Alternate selection still chooses takes; it does not crossfade them
unless separate selected layers have crossfade settings.

## Named Articulations

Declare articulation IDs, a default, and optional key/control bindings.

The articulation table requires a duplicate-free `ids` list, which may be empty,
and an optional `default` naming one of them. With no default, gated slots remain
silent until an articulation is selected. A keyswitch without an articulation
clears selection and may consume its note. Key and control binding arrays default to empty.
Slot articulation lists are duplicate-free references; an empty list means
eligible in every articulation. Tags remain descriptive.

Selection is independent per part. Key bindings have unique unrestricted
integer `key` values. `behavior` is `latched` (default) or `momentary`;
`consume` defaults to true. A latched trigger changes the persistent selection.
A momentary trigger overrides it until Release for that exact trigger ID.
The most recently started still-held momentary switch wins; latched changes
continue underneath it. Releasing the last momentary switch exposes the
latest persistent selection. Repeated keys do not require FIFO matching.

Switch releases are immediate, not deferred by sustain. A consumed switch
retains its trigger-ID ownership but creates no sample voices or release
samples. With `consume = false`, update articulation before selecting samples
for the same trigger; those voices retain their captured articulation.

A control binding names a declared control and an inclusive, ordered
`minimum_value`/`maximum_value` interval within its polarity's domain.
Intervals for the same control cannot overlap. Only part-scoped ControlChange
events drive these bindings. A match changes persistent selection; an
unmatched value leaves it unchanged. Bindings are latched and do not consume
the event: it may also affect sustain and modulation.

Selection affects newly selected slots and never remaps existing voices.
The current sample preparer reads the part's current articulation for release,
logical-release, and sustain slots as well as starts. `ActiveTrigger` retains
selected template IDs, but no separate onset articulation; preserving the onset's
articulation for release selection would require an implementation change.
Switching does not reset alternate-selection counters. Loading/resetting
restores defaults and clears held switch IDs without generating samples.
Control initialization does not execute bindings.

Future execution conformance must cover consumed/playable switches, exact-ID releases of repeated
keys, nested momentary switches, latched changes underneath them, independent
parts and control gaps. Onset-articulation retention is not an implemented guarantee.

## Playback Direction

`direction` is exactly one of:

| Value | Traversal of the selected interval |
| --- | --- |
| `"forward"` | First selected frame to last selected frame |
| `"backward"` | Last selected frame to first selected frame |
| `"mirror"` | First to last, then back to first, once |

For selected frames `A B C D`, the traversal sequences at native rate and
original pitch are:

```text
forward:  A B C D
backward: D C B A
mirror:   A B C D C B A
```

The turning frame is not duplicated. For `N` selected frames, mirror traverses
`2 * N - 1` frames; a one-frame sample plays once in every direction. At other
pitch or output rates, resampling follows that traversal. Reversal affects
frame order, not channel order or sample polarity.

Mirror alone does not mean indefinite ping-pong looping. Without an explicit
loop, every direction eventually exhausts its selected material.

The instrument supplies the default direction. A slot's explicit direction replaces
that default, so a backward instrument plus a backward slot still plays backward,
not forward. Direction is not a numeric modulation target.

## Sustain Loops

A named slice may declare a loop inside its interval. Loop boundaries never
inherit from instrument settings because they address one particular asset.

Both boundaries are required native-frame integers. They define a half-open
interval inside the trimmed sample containing at least two frames. `mode` is
`"until_release"` (default) or `"through_release"`; `crossfade_frames` defaults
to zero. `repeat_count` is either null (unbounded) or a nonnegative number of
additional traversals after the first pass through the loop. When the count is
exhausted, playback continues toward the trimmed sample boundary without another
wrap or reflection. A release can disable an `until_release` loop earlier; a
`through_release` loop still ends if its finite count is exhausted. Loops require
effective playback mode `while_held`, so a one-shot voice
cannot loop forever without a release event.

Whole-sample `direction` selects the approach to the loop. The loop's own
`direction` independently selects forward wrapping, backward wrapping, or mirror
reflection between its boundaries without repeating either turning frame. For loop
material `B C D`, its steady mirror sequence is `B C D C B C D ...`.

On release, `until_release` disables future wrapping and reflection immediately.
Playback continues in its current direction toward that trimmed sample boundary
while the release envelope runs. It does not jump to the tail. If a boundary
and release coincide, process release before the boundary transition.
`through_release` keeps repeating until amplitude release completes, even
when its final target is nonzero; it does not subsequently play a tail. Exhaustion or envelope completion,
whichever comes first, ends the voice. If release occurs before loop entry,
`until_release` never enters repetition.

For forward or backward wrapping, a positive crossfade overlaps the final `M`
frames of the traversal with the first `M` frames of its next traversal. Require
`M >= 2` and `2 * M < loop_length`. At overlap position `j`, use incoming weight
`j / (M - 1)` and outgoing weight `1 - j / (M - 1)`. After the overlap, resume
at frame `M` of the next traversal, not at its already-consumed first frame.
Thus the repeat period is `loop_length - M` native frames. All channels use the
same weights; fractional playback positions interpolate this traversal.

If release disables repetition during an overlap, finish that overlap and then
continue from the incoming head without further wrapping. Mirror requires
`crossfade_frames = 0`: its reflection already joins adjacent frames, and this
version does not define a separate turn-smoothing algorithm.

Future execution conformance must cover forward/backward wrapping, mirror endpoint order,
crossfade duration and head consumption, release before entry, release during
an overlap, and both release modes. The no-loop direction examples remain
unchanged.

## Repeated Whole-Sample Playback

A slot may set `play_count` to a positive integer when its effective playback
mode is `one_shot`. The selected sample interval plays that many times in its
chosen direction. The amplitude envelope and other voice state start once and
continue across each sample restart; they are not retriggered. The voice ends
on envelope completion or after the final traversal, whichever occurs first.
This is distinct from a loop's `repeat_count`, which repeats only the loop
interval and then continues into the sample tail.

## Delayed Voice Start

`start_delay_seconds` on a slot defaults to zero. A positive value postpones
the start of both sample traversal and all voice envelopes by that duration.
For a start-triggered slot, release of the owning trigger before delayed start
cancels the pending voice without sounding. For a release-triggered slot, the
release event creates the pending voice and starts this timer; that same event
does not cancel it. This differs from an
amplitude envelope's delay phase, which begins when the voice itself starts.

## Final Sample Fade

`end_fade_seconds` on a slot defaults to zero. A positive value applies a
linear amplitude fade during the final seconds before the sample reaches its
trimmed playback boundary. The duration is measured in playback time, not
source frames, so pitch changes do not change the requested fade time. It is
independent of the amplitude envelope and does not begin merely because a note
is released. An early release or envelope completion can end the voice before
the fade is reached.

The fade occurs once at final exhaustion, not at each loop or whole-sample
repeat. Remaining distance includes all finite repeats, mirrored turns and
committed crossfades. An indefinite loop has no predicted exhaustion until its
release policy allows it to exit. At each output frame before onset, divide
remaining source distance by current playback speed; start the fade when that
time is no greater than the authored duration. Latch that frame and run the
linear gain from one to zero over the authored duration. Subsequent pitch
changes do not retime it: faster playback may exhaust the source early, while
slower playback ends when the fade reaches zero. The fade multiplies final
voice output after filters, independently of envelope and retirement gains.

## Release And Sustain Samples

Each slot's `trigger` is `start` (default), `control`, `release`, `logical_release`,
`sustain_press`, or `sustain_release`. Control-triggered voices follow the
separate condition rules above. Release means the explicit input event;
logical release means the eventual release after sustain deferral.

Sustain is absent by default. When present it requires a declared unipolar
`control` and a finite threshold in `(0, 1]`, default 0.5. State is per part,
initially derived from the control's default. Only part-scoped changes to that
control affect sustain. Values at or above threshold mean pressed; only
threshold crossings generate sustain-transition samples. Sustain slots are
invalid without a sustain declaration. No control name has hidden semantics.

A Trigger creates an instance identified by `(part, trigger_id)`, owning its
voices, original key, velocity, target pitch, and trigger-scoped
controls. The host must not reuse this identity while it is held or owns live
voices, including release voices. Repeated keys have distinct IDs and may be
released in any order. Retain ownership of held triggers even after their
audio exhausts. Ignore unknown or already-released Release events.

Same-key policy retires prior voices before starting any layer of a new trigger.
The preparer reserves capacity for the complete new start batch, retiring older
voices according to the overflow policy. If the batch alone exceeds
`maximum_voices`, preparation rejects it rather than dropping selected layers.

On the first matched Release, generate `release` once if at least one original
start voice is active and neither released nor choked. If sustain is off,
generate `logical_release` under the same condition and release owned
while-held voices. Otherwise defer logical release until sustain goes off.
Recheck original-voice eligibility then: exhausted/choked triggers generate
no release samples. Sustain never resurrects a voice or interrupts a release
already underway.

Release samples use the original key, velocity, and target pitch,
not values inferred from the release event. Articulation selection follows the
current-part limitation above. They share their owning trigger's
live controls. Selection happens once per trigger instance, not once per layer.
Release and sustain samples require one-shot playback without loops; they
cannot recursively generate releases. Chokes are not input Release events.

Sustain samples use their own `event_key` and the current control value as
velocity, including zero on release. They have no owning performance trigger:
trigger-scoped routes use control defaults and cannot be addressed later.
Within one selection set and sustain-trigger kind, alternatives must share
`event_key` so they participate in the same selection decision.

On sustain release, update state, process pending triggers in their start
order, and generate sustain-release samples. All voices derived from one
input event form an atomic batch; select them before applying chokes to
previous voices. Later events at the same frame retain input order.
Reset clears held/deferred IDs and restores control-derived sustain state
without generating release or sustain samples.

Future execution conformance must cover out-of-order releases of repeated keys, zero-velocity
starts and sustain releases, independent parts, sustain deferral, exhausted
voices, ignored duplicate releases, and nonrecursive tails.

Portable selection vectors in [selection.json](../conformance/selection.json)
pin multi-draw random progression and three shuffle bags. Common sample/synth
[lifecycle cases](../conformance/instrument-lifecycle.json) pin action ordering,
layered replacement and cross-part choke isolation. Both preparers consume the
same lifecycle cases in tests; sample-specific inheritance and serialized synth
settings retain their dedicated regression tests.

## Yamaha Synth Voice Templates

Synth instruments can use `yamaha = "dx7"` or `yamaha = "tx81z"` templates.
These are dedicated Yamaha profiles, separate from the general `fm` graph.
The `patch` field contains the lossless voice payload encoded as hexadecimal:
155-byte VCED or 128-byte packed voice data for DX7, or 93-byte VCED for TX81Z.
TX81Z also requires an explicit `additional` field containing its 23-byte ACED
payload in hexadecimal. Pairing is never inferred from neighboring messages.
Python templates retain the existing DX7Voice/TX81ZVoice/TX81ZAdditional objects;
JSON and TOML serialization use the hexadecimal fields.

Structural admission preserves parameter bytes even when they are outside a
playable profile. The rendering consumer must reject unsupported or malformed
parameters before starting audio. Yamaha operator envelopes come from the
patch; a second generic amplitude envelope is not accepted on these templates.

Yamaha modulation targets use `name = "yamaha"` and one of `pitch_bend`,
`modulation_wheel`, `breath`, or `foot` as the parameter. Each uses unit `ratio`
and default zero. Pitch-bend domains must stay inside -1 through 1; the other
controller domains must stay inside 0 through 1. Existing bindings, scoped
sources, mappings and smoothing deliver these normalized controller positions.
They describe control inputs, not tuning cents or direct audio gain. Rendering
consumers apply the model's controller assignments and must reject unimplemented
targets. Patch bytes are not rewritten when controller values change.

DX7 templates also carry `performance` settings outside the lossless patch.
`pitch_bend_range` is an integer from 0 to 12 semitones, default 2.
`modulation_wheel`, `breath` and `foot` each have an integer `range` from 0 to
99 and independent boolean `pitch`, `amplitude` and `eg_bias` assignments.
Each range defaults to zero and each assignment defaults to false. These are
portable neutral defaults, not recovered hardware settings. The original DX7
voice dump contains none of these function settings. See the
[DX7 owner's manual, Function Parameters](https://homepages.abdn.ac.uk/d.j.benson/pages/dx7/manuals/dx7-man.pdf).

Shared synth preparation retains template identity, key, resolved pitch, channel
routes and lifecycle actions. Yamaha VoiceStart actions additionally carry the
original 0–1 velocity directly, including for release-triggered notes; other
synth starts retain their existing control-context velocity contract. Sustain
triggered Yamaha voices use the control value that selected the voice. These
portable definitions and traces do not implement a synthesis engine.
