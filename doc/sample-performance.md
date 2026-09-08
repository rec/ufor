# Sample performance requirements

These musical behavior requirements were retained from the Recsam specification
when its types moved to Ufor. The [native instrument format](instrument-format.md)
defines the implemented data. This appendix records the intended future player
behavior, not implemented scheduling, audio processing, or completed action traces.
The next preparation milestone must turn these requirements into portable traces.
Any conflict with the new shared envelope/LFO model is resolved in favor of
[that model](modulation-format.md): exact cumulative times, whole envelope
overrides, and separate completion/lifetime policy.

Instrument and slot processing remain per voice, before mixing. Phase during
LFO delay follows the shared model. Native events use tick/ordinal ordering;
references below to equal-frame input order mean that explicit ordering.
Random/shuffle probabilities do not yet specify a portable seeded algorithm.

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

Cycle is fully deterministic. Random and shuffle define selection probabilities
but not cross-player seeded reproducibility; the separate reproducible-variation
proposal remains unimplemented. Do not claim that a seed alone guarantees
identical selection across engines.

Future execution conformance must cover layering outside sets, several independent sets,
candidate filtering before selection, one/zero eligible candidates, shuffle
refill boundaries, and invariance under audio block-size changes.

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
trigger time; live-input weights follow the smoothing rules below.

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

The articulation table requires a nonempty, duplicate-free `ids` list and a
`default` naming one of them. Key and control binding arrays default to empty.
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

Selection affects future start and sustain-transition triggers, never remaps
existing voices. Release and logical-release samples use the original
trigger's captured articulation. Sustain samples use the part's current one.
Switching does not reset alternate-selection counters. Loading/resetting
restores defaults and clears held switch IDs without generating samples.
Control initialization does not execute bindings.

Future execution conformance must cover consumed/playable switches, exact-ID releases of repeated
keys, nested momentary switches, latched changes underneath them, independent
parts, control gaps, and captured articulation for release samples.

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
to zero. Loops require effective playback mode `while_held`, so a one-shot voice
cannot loop forever without a release event.

Forward playback enters from the trimmed start, then repeats the loop toward
increasing frames. Backward playback enters from the trimmed end, then repeats
it toward decreasing frames. Mirror enters from the trimmed start and reflects
between loop boundaries without repeating either turning frame. For loop
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

## Release And Sustain Samples

Each slot's `trigger` is `start` (default), `release`, `logical_release`,
`sustain_press`, or `sustain_release`. Release means the explicit input event;
logical release means the eventual release after sustain deferral.

Sustain is absent by default. When present it requires a declared unipolar
`control` and a finite threshold in `(0, 1]`, default 0.5. State is per part,
initially derived from the control's default. Only part-scoped changes to that
control affect sustain. Values at or above threshold mean pressed; only
threshold crossings generate sustain-transition samples. Sustain slots are
invalid without a sustain declaration. No control name has hidden semantics.

A Trigger creates an instance identified by `(part, trigger_id)`, owning its
voices, original key, velocity, target pitch, articulation, and trigger-scoped
controls. The host must not reuse this identity while it is held or owns live
voices, including release voices. Repeated keys have distinct IDs and may be
released in any order. Retain ownership of held triggers even after their
audio exhausts. Ignore unknown or already-released Release events.

On the first matched Release, generate `release` once if at least one original
start voice is active and neither released nor choked. If sustain is off,
generate `logical_release` under the same condition and release owned
while-held voices. Otherwise defer logical release until sustain goes off.
Recheck original-voice eligibility then: exhausted/choked triggers generate
no release samples. Sustain never resurrects a voice or interrupts a release
already underway.

Release samples use the original key, velocity, target pitch, and articulation,
not values inferred from the release event. They share their owning trigger's
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
