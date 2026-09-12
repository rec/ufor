# Modulation profile 1

This profile defines portable envelopes and LFO controls. It includes frozen
definitions, exact clock coordinates, event/state transitions, and scalar
reference calculations. It does not render audio, schedule devices, interpret
MIDI pedals, allocate voices, or implement a sampler. Existing Recsam and Tuney
engines are not changed by adding this profile.

`envelope` and `lfo` are common score kinds, using the existing `format =
"recs"`, `version = 3`, `name`, `title`, and `body` fields. Both round-trip through
the common TOML codec. The generated schema and
[conformance/modulation.json](../conformance/modulation.json) accompany the
Python reference in `ufor.envelope` and `ufor.lfo`.

Autonomous light controls also use `envelope.Curve`: an initial value and shared
segments, with final-value holding or whole-curve repetition. Curve values may
exceed the normalized domain, for example a gain above one. Trigger/release
`Envelope` retains its normalized bounds. The light profile adds `part` scope
and uses the same modulation evaluation; see [light-format.md](light-format.md).

## Clock, scope, and observation

Each definition chooses one clock: `seconds` or `beats`, where one beat is a
quarter note. Durations, positions, cycles, duty fractions, and rates use exact
rationals. Wire values are strings such as `"1/3"`; integers are also accepted
on input. Decimal strings such as `"0.1"` mean exactly 1/10. Floating-point
numbers and booleans are rejected in these fields. Canonical output is a
reduced fraction string, or an integer string when the denominator is one.
This is rational-number notation, not the frequency-expression language:
exponentiation and arithmetic expressions are not accepted here.

The host supplies monotonically increasing coordinates in the chosen clock.
For a beat envelope, a tempo change alters elapsed seconds but does not restart
or rescale the segment's beat progress. At 120 BPM until second 1 and 60 BPM
afterward, beat positions at seconds 0, 0.5, 1, and 2 are 0, 1, 2, and 3. A
four-beat linear attack is respectively 0, 0.25, 0.5, and 0.75 complete. An LFO
at 1/4 cycles per beat has those same phases. Neither generator owns the tempo
map; the current recording `Timebase` remains physical. A beat-clock host must
supply the integrated musical position, not pass seconds to a beat definition.

No segment is rounded separately to an audio or control frame. Boundaries are
exact sums of durations. A host observes the value at its actual rational
sample position. An event between observations affects the next observation,
using its original time to compute interrupted values and subsequent progress.
Evaluation frequency and host block size cannot move an event or boundary.

`scope` is `voice` by default or `instrument`. The owner allocates state for
each instance, separately from the immutable definition. A shared instrument
LFO has one state per instrument instance; all joining voices observe that
state. A voice source has state per voice, including separately layered voices.
Two uses of a score never share state merely because their definition IDs
match. Gate routing to an instrument envelope must be explicit; it is not
implicitly the OR of every key in the instrument.

## One envelope representation

`Envelope` has an `initial` level, nonempty `segments` and `release` lists,
`hold`, `retrigger`, clock, scope, and polarity. Every segment has a
nonnegative `duration`, `target`, and finite `curve` (default zero). Targets
and the initial value lie in [0,1] for `unipolar`, the default, or [-1,1] for
`bipolar`. These are dimensionless control levels; a route assigns their
meaning as gain, cents, a frequency ratio, light intensity, or another quantity.

On a trigger, traverse `segments`. On release, abandon that traversal and
traverse `release` from the current level. Each list has its own local segment
indices starting at zero. The last on-segment target is held when `hold = true`
(the default). With `hold = false`, finishing the on-list completes a one-shot
contour. Finishing the release-list always completes the contour. Completion
holds its terminal value, which need not be zero. A host chooses whether a
particular amplitude envelope's completion retires a voice; a modulation
envelope's completion alone does not.

ADSR is an authoring preset that expands into this representation. There is
no second ADSR evaluator. Delay and hold are ordinary segments whose target
equals their entry level. For example, delay 1/10 second, attack 1/2 second,
hold 1/10 second, decay 1/4 second to 0.6, then sustain and release:

```toml
format = "recs"
version = 3
name = "soft-amplitude"
title = "Soft amplitude"
kind = "envelope"

[body]
clock = "seconds"
scope = "voice"
initial = 0.0
hold = true
retrigger = "current"

[[body.segments]]
duration = "1/10"
target = 0.0

[[body.segments]]
duration = "1/2"
target = 1.0
curve = 5.0

[[body.segments]]
duration = "1/10"
target = 1.0

[[body.segments]]
duration = "1/4"
target = 0.6
curve = -5.0

[[body.release]]
duration = "1/2"
target = 0.0
curve = -5.0
```

For entry value a, target b, duration d > 0, and elapsed time t in [0,d],
let u = t/d. The value is `a + (b-a)*F(u,k)`, where k is `curve`:

```text
F(u,0) = u
F(u,k) = (exp(k*u)-1)/(exp(k)-1), when k != 0
F(0,k) = 0 and F(1,k) = 1 exactly
```

Positive k makes progress slow initially and fast near the end; negative k
does the reverse. The rule is independent of whether b is above or below a.
There is no asymptotic tail or logarithm of the target, so decay to zero and
crossing zero are well defined. Implementations should use `expm1` and the
algebraically equivalent negative-exponent form for positive k to avoid
overflow. Curve zero is the exact linear branch.

Segments occupy half-open intervals. At an endpoint, consume the segment and
any following zero-duration segments in order before observing or applying
an event. A zero-duration segment immediately sets its target. This also
applies at trigger and release time, and finite lists cannot create an
infinite zero-time transition loop.

## Envelope events and state

Events contain rational `at`, nonnegative integer `ordinal`, and `action`:
`trigger` or `release`. Process them in strictly increasing `(at, ordinal)`
order within a source instance. Ordinals break equal-time ties; they may start
again at a later time. The host merges inputs and assigns these ordinals before
delivery. The reference rejects backward events and duplicate equal-time
ordinals. It does not silently sort or impose an action-type priority.

At a timestamp, advance the contour through completed/zero-time segments,
apply each event in ordinal order, then observe. Consequently trigger followed
by release at the same timestamp differs from release followed by trigger.

| Input/state | Result |
| --- | --- |
| Initial state | Idle at `initial`; no implicit trigger |
| First trigger | Begin on-list at `initial` |
| Active trigger with `current` (default) | Restart the complete on-list from the observed level |
| Active trigger with `reset` | Restart the complete on-list from `initial`, allowing a jump |
| Active trigger with `ignore` | Continue the current traversal or held level |
| Trigger after completion | Start again; `current` uses the terminal value, other policies use `initial` |
| Release during any on-segment or held state | Begin release-list from the exact current value |
| Release while idle, completed, or already releasing | No change to the contour |

Restarting the complete on-list includes any authored delay. `current` promises
no jump at its entry, but an authored zero-duration segment can still jump.
Release durations are measured anew and in full from the release event; they
are not shortened in proportion to the current level. Definition edits and
changes to segment durations require a new prepared instance in profile 1.

`EnvelopeState` records the last event coordinate/ordinal, current list
(`idle`, `on`, or `release`), its start coordinate, and its captured start value.
`envelope_at` returns value, status (`idle`, `running`, `held`, or `complete`),
and the active segment index when running. Observations do not mutate state.

Physical key release and logical gate release are distinct. Sustain-pedal and
legato policy belongs to the future instrument adapter: it may defer a gate
release or omit a retrigger. Once a logical release is delivered, the envelope
does not reinterpret it. Choke, voice stealing, release samples, and transport
stop are also instrument/host decisions, not alternate spellings of release.

## LFO phase, resets, and activation

`LFO.rate` is nonnegative cycles per clock unit. Zero freezes phase. `phase`
is the reset phase in [0,1), default zero; `duty_cycle` lies in [0,1], default
1/2. Both are rational, so transition comparisons are exact. Shape names reuse
`ufor.oscillator.Waveform`: sine, square, triangle. For phase p and duty d:

```text
sine:     sin(2*pi*p), ignoring d
square:   +1 when p < d, otherwise -1
triangle: 2*p/d-1 when p < d, otherwise (1+d-2*p)/(1-d)
```

At d=0, only the falling triangle branch is used; at d=1, only the rising
branch is used. The triangle peak is +1 at p=d for 0<d<1. A square is -1
exactly at its falling transition. These are Tuney's documented equations.
They describe single control observations, not band-limited audio generation.

The state stores an anchor position a, its phase p, current rate r, activation
start, and last event ordinal. At x >= a, phase is exactly
`(p + r*(x-a)) modulo 1`. A `rate` event first advances to its position using
the previous rate, then installs the new rate without changing phase or the
activation start. Profile 1 rate automation is piecewise constant; continuous
rate ramps need a separately specified integration contract.

`reset` selects which host events reset phase and activation age:

| Policy | Trigger event | Transport event | Explicit reset event |
| --- | --- | --- | --- |
| `free` | Ignore | Ignore | Reset |
| `trigger` (default) | Reset | Ignore | Reset |
| `transport` | Ignore | Reset | Reset |

A reset uses the definition's phase but retains the current rate. Transport
events denote explicit starts/discontinuities; they are not ordinary host block
boundaries. Stopping the transport stops advancement of its clock. A free
source that should keep running needs a continuously advancing host clock.
Absolute song-grid alignment is obtained by starting at the designated origin
and replaying its rate/reset events, not by resetting at the requested seek
position. Scope and reset policy are independent: joining a shared instrument
source is not itself a trigger event to that source.

`delay` and `fade_in` are nonnegative durations, default zero, measured from
activation or the latest applicable reset. Phase advances during both. The
observation is `(phase, value, weight)`: waveform value is always bipolar;
weight is zero before delay, ramps linearly from zero to one during fade-in,
then is one. A zero fade makes activation immediate at the delay endpoint.
Rate changes do not restart delay or fade. A separate envelope can describe
fade-out when a future instrument route combines their controls; profile 1
does not add a second LFO stop/tail state machine.

## Mapping and combination contract

The generators output dimensionless values. Instrument/processor routes must
name their source instance, structured target `{part, parameter}`, mapping,
operation, and target domain. The embedded `ufor.modulation.Modulation`
collection now implements [typed routes](instrument-format.md#modulation-routes)
for the later instrument/processor bodies. Reusable timeline automation reaches
an arrangement through its own typed control clip. The composition contract is:

1. Resolve one base value, including authored replacement automation.
2. Map each source value to an additive amount in the target's units or a
   dimensionless multiplier. No implicit cents/Hz/dB conversion is allowed.
3. Apply source activation weight w **after** mapping: an additive amount a
   becomes `w*a`; a multiplier m becomes `1+w*(m-1)`.
4. Compute `(base + sum(additive amounts)) * product(multipliers)`.
5. Check the target's declared domain. Reject an out-of-domain result; clipping
   requires a separately explicit operation, not a hidden host default.

Thus an inactive LFO contributes zero to addition and one to multiplication,
even if its mapping assigns a non-neutral amount to waveform value zero.
For example, a multiplier mapped to 0.2 at weight 0.5 contributes 0.6, not 0.1.
With base 10, additive amounts 2 and -1, and multipliers 0.5 and 2, the result
is 11. Hosts reduce routes in stable source/route-ID order for predictable
floating-point behavior. List ordering never selects a winning modulation.
Only one replacement-automation producer is allowed per parameter; mixing
several requires an explicit upstream operation. Feedback and live modulation
of envelope segment definitions are outside this profile.

## Seeking and conformance

Seek by replaying events from the instance origin, optionally starting with
a saved state bound to that exact definition and input history. Querying before
the state's last event is an error; the reference does not guess the previous
rate, gate, or phase. An observation in the future does not advance the stored
state. Calls inserted at different block boundaries therefore cannot alter
later observations. Independent instances and state JSON round trips are
covered by the tests.

The portable cases give complete definitions, ordered events, and named
post-event observations. Rational positions/phases, segment indices, event
ordering, and status compare exactly. Floating control values use absolute
tolerance 1e-12, including transcendental curves and sine. No WAV data or
48 kHz audio buffers are generated. Valid cases round-trip through TOML; invalid
scores include negative durations/rates, invalid polarity/phase/duty, and
unsupported loops/random sources.

## Changes from Recsam and remaining boundaries

| Existing declaration or behavior | Profile 1 treatment |
| --- | --- |
| Fixed DAHDSR fields | Expand to one segment list plus release list; hold is a property of completion |
| `linear` / `exponential` attack | Curve 0 / +5 |
| `linear` / `exponential` decay or release | Curve 0 / -5, reproducing the old reversed curve |
| Per-stage `ceil(seconds * sample_rate)` | Exact cumulative times, observed on the host's grid |
| Release from current level; repeated release ignored | Preserved |
| Per-field slot envelope inheritance | Removed; native slots store a complete override or inherit the instrument envelope |
| Fixed voice retrigger | Explicit current/reset/ignore policy |
| Hz-only LFO, fixed rate | Seconds or beats; exact phase-preserving rate events; zero rate may freeze |
| Phase frozen during LFO delay | Phase advances; to preserve the old phase at activation, use reset phase `(old_phase-rate*delay) mod 1` |
| LFO delay contributes neutral route amount | Preserved through activation weight; fade-in added |
| Sine/symmetric triangle only | Tuney shape vocabulary also permits square and explicit rational duty/skew |

An attack interrupted during delay, a curved decay to zero, an ordinary ADSR,
and a bipolar one-shot are represented without extra engines. A looped contour
would additionally require loop entry/exit, release-from-loop and zero-time
cycle rules. It is intentionally rejected in this first profile. Random and
sample-and-hold sources, audio-rate realization, band-limiting, continuous rate
automation, generic graph execution, and a sampler remain deferred.

Shared performance events and typed modulation routes are now implemented.
The native instrument and SFZ cutover is implemented in
[the instrument format](instrument-format.md). Sample settings use these exact
envelope/LFO definitions and the shared route evaluator; the old Recsam models
are removed. Prepared voice state and audio generation remain deferred.

## Additional work beyond the prompt

None.
