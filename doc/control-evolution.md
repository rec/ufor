# Instrument control evolution

This contract specifies scalar control trajectories and the preparation data
needed by synth and sample renderers. It adds no audio engine, device clock,
MIDI policy, or buffer API. The defining modules are `samples.controls`,
`instrument_trace`, `synth`, and `samples.playback`.

## Smoothing and interruption

A `ControlBinding.smoothing` duration is a finite linear transition in the
declared source domain, measured in exact rational seconds. Apply it before
route mapping, not after summing modulation at the destination. Zero means an
immediate step. There is no additional implicit destination smoothing.

For target b received at time k, capture the preceding trajectory's value a at
k. For smoothing duration S and observation time x >= k:

```text
S = 0: value(x) = b
S > 0: value(x) = a + (b - a) * min((x - k) / S, 1)
```

At the endpoint return b exactly. If another target arrives before completion,
evaluate the current trajectory at that time and start a new full-duration ramp
from that value. A positive-duration change has no jump at entry; a zero-duration
change does. Same-time changes apply in increasing ordinal order. Repeated equal
targets follow the same interruption rule, rather than being discarded.

`initial_control(declaration, at, smoothing, value=None)` initializes from the
declaration default or an explicit initial value, with no ramp from zero.
`control_event` accepts an ordered `ControlValueEvent` and returns replacement
`ControlState`. `control_at` observes without mutating state. These scalar events
use rational seconds and are distinct from native-tick performance input events.
The caller converts ticks using the stream's exact rational timebase.

The state contains the event coordinate/ordinal, captured starting value, target,
and smoothing duration. It round-trips through JSON and is sufficient to resume
this scalar trajectory with the same declaration. Earlier queries require replay;
observing a future value does not consume time or prevent an intervening event.
Negative durations, invalid control values, and unordered events are errors.

At output rate R, observe at exact times n/R. Do not round the duration to a number
of frames or repeatedly subtract a block duration. For example, S = 1/32000 spans
1.5 frames at 48 kHz: values after a zero-to-one change are 0, 2/3, and 1 on the
first three samples. An observation's block partition cannot affect the value.

## Scope, initialization, and lifetime

Instrument, part, and trigger controls are separate contexts. Scope bindings select
a context explicitly; there is no implicit instrument/part/trigger override stack.
All controls begin at their declared defaults except explicit trigger-initial
values. An initial trigger value does not modify its parent part or instrument.

Instrument and part context history continues even while no voices are sounding.
A joining voice observes the existing trajectory, including a ramp already in
progress. Bindings sharing a context, control, and smoothing duration observe one
trajectory; differing smoothing durations require distinct trajectories. They can
share the same raw control events, not the same smoothed value. Generate those
trajectories from the context's history, not from its most recent target alone.

Trigger context starts once per accepted onset. Layered voices and later
release-triggered voices for that onset use the same context and captured velocity.
Physical release and logical retirement do not reset its controls: release tails
can still consume subsequent addressed changes. Keep the context while any audio
voice needs it, independently of the preparer's logical voice list.

The existing preparation rules determine when a trigger ID can be reused. Reuse
creates a new context; it never attaches an old audio tail to the new onset's
controls. A later control change addresses the latest onset for that part/ID.
An old tail retains its old trajectory and completes any ramp already in progress,
but no longer receives changes addressed to the reused ID. A trigger-scoped
observation with no preceding context has no target: consumers ignore it, do not
store it for a future onset, and do not broadcast it to another scope.

Voices without a trigger ID, such as sustain-transition samples, use defaults for
trigger-scoped sources and cannot be addressed in that scope. Sustain and other
selection/gate decisions use raw performance values under their existing rules;
expression smoothing must not delay a logical release or change sample selection.

## Prepared trace contract

Both preparers emit `instrument_trace.TriggerContext`, with kind
`trigger_context`, once for every accepted Trigger. It carries the native tick
and ordinal, part, trigger ID, velocity, and the complete initial control map
(declaration defaults replaced by the Trigger's explicit values). It appears
before that onset's retirements and voice starts, even if selection produces no
voices. Initialization does not create an audio voice or rerun selection.

The pair of context action coordinate and addressed part/trigger identifies an
onset's context without inventing another user-authored ID. Process actions in
`(tick, ordinal)` order and retain their trace-list order for ties. A performance
event can produce several actions at the same coordinate. Voice starts with a
trigger ID attach to its latest preceding context; release-triggered starts do
not initialize another context.

Existing `control` actions retain subsequent raw addressed observations, including
changes while silent or during release. The definition, context initialization,
and ordered observations together provide the control history. The trace does not
flatten that history into one value per voice, emit per-sample controls, or apply
smoothing to its stored values. Renderers must handle the new context action.

Lifecycle snapshots remain observational and omit complete control/sustain/DSP
state. They are not resumable preparation checkpoints. Replaying a full trace
reconstructs contexts; resuming an audio engine needs its own snapshot containing
all active control trajectories and context associations.

## Pitch composition

Keep pitch resolution and musical key selection separate. `Trigger.pitch_hz` is
already resolved from the caller's tuning. A renderer never retunes from the key
or reapplies the tuning system that produced that frequency.

For a synth, preparation puts `Trigger.pitch_hz + frequency_offset_hz` in
`VoiceStart.pitch_hz`. Release-triggered voices use their own template's offset
with the original trigger pitch. This prepared frequency is the untuned base for
subsequent processing modulation; it does not include `processing.tuning_cents`.

Resolve that voice's tuning parameter with the shared modulation evaluator. Its
base is the static `processing.tuning_cents`, or an explicit replacement where
supported. Additive/multiplicative routes produce the final cents value C:

```text
synth frequency = prepared pitch_hz * 2 ** (C / 1200)
```

`synth.frequency` is the scalar reference for this step. Do not add the Hz offset
again, and do not add the static cents value again after route evaluation. For
onset 440 Hz, offset 5 Hz, static 600 cents and a route adding 600 cents, preparation
returns 445 Hz and realization returns 890 Hz, not a twice-detuned frequency.
Inputs to realization are validated positive prepared frequencies and finite
resolved tuning values. A renderer must reject unsupported or invalid results.

For a sample, `VoiceStart.pitch_hz` preserves the original trigger pitch. Resolve
instrument and effective slot/group tuning independently using their own static
bases and supported routes, then add their final cents values. Add resolved
`variation.pitch_cents` once after that combination:

```text
tracking ratio = pitch_hz / reference_pitch_hz  (when pitch_tracking is true)
tracking ratio = 1                             (otherwise)
pitch ratio = tracking ratio * 2 ** ((combined tuning + variation) / 1200)
native frames per output frame = pitch ratio * native_rate / output_rate
```

`samples.playback.pitch_ratio` takes the Mapping, onset pitch, combined final
tuning, and resolved variation. A tracked mapping requires pitch; an untracked
mapping ignores it, but still applies tuning and variation. The helper does not
fold in sample rates, direction, interpolation, or time stretching.

Controls may change tuning during a voice's lifetime and release. Realization
updates future oscillator phase increments or sample traversal increments while
preserving current phase/position. Changing tuning does not select another slot,
reset an envelope, or recompute phase from total age and the latest frequency.
Audio integration and sample interpolation belong to the engine specification.

## Conformance and remaining scope

[control-evolution.json](../conformance/control-evolution.json) contains portable
smoothing, prepared-context, and pitch examples. Scalar floating results use
absolute tolerance 1e-12; rational coordinates, ordering, context values, and
discrete decisions are exact. The same trace cases run against both preparers.
Scalar tests include interruption, same-time changes, immediate updates,
fractional-frame endpoints, large timestamps, additional observations, and state
restoration. The context case includes silent selection, part isolation, changes
during release, and reuse of a trigger ID.

This contract does not add live envelope-definition editing, LFO rate ramps,
audio-rate filters, structural voice edits, automation-to-instrument wiring,
or a resumable instrument preparer. Existing envelope/LFO/route contracts remain
the definitions of their behavior. Engines must declare the subset they support.

## Additional work beyond the prompt

None.
