# Portable live-effect graphs

`ufor.audio_effects` defines fixed acyclic processor graphs for offline and live audio effects.
enge owns their numerical realization. A graph belongs to a voice, instrument,
master, or host attachment and has named audio inputs, processor nodes, explicit
connections, and one public output. These are embedded models, not a root score
kind accepted by the common codec. Hosts attach graphs to their owners explicitly.

Every processor has a stable local ID. Audio input ports are fixed by processor
type and are distinct from scalar modulation. Gain, waveshaper, resonant filter,
delay, and granulator processors have `input`; multiplication has equal-layout `carrier`
and `modulator` ports. Compression has `input` and `detector`, whose layouts may
differ. Connections may fan out, but a port has one source and
implicit mixing is forbidden. Preparation validates all references, layouts,
required ports, whole-program cycles, and reachability before establishing a
canonical topological order. A producer executes once per span even when its
output fans out.

Graph inputs name the stream presented by their owner. Exactly one has `main`
source. Host and instrument graphs may additionally reference declared host
streams or instrument pre-effect/post-effect outputs. A per-voice graph receives
only its own source stream; dynamic voices cannot name one another. Consumers
must expand all graph and stream references before checking cycles.

## Processor profile

Reverb maps mono or named stereo input to named stereo output. Other processors
preserve the primary input layout in this profile. Multiplication
requires identical carrier and modulator layouts and multiplies corresponding
samples. Wet/dry uses the designated dry input and linear interpolation:

```text
output = (1 - mix) * aligned_dry + mix * wet
```

Bypass ramps toward dry over `bypass_fade_frames` (default 64) while processing
and state advancement continue. Authored mix remains independent, so unbypass
returns to its current value. Tail retirement uses the graph's
`tail_retirement_fade_frames` (default 64). Filters and delays declare
`tail_threshold` (default `1e-12`) and `state_floor` (default `1e-30`, strictly
below the threshold). Only designated decaying state may be trimmed. These are
serialized settings, not fixed constants that a host may silently substitute.

`TapDelay` declares a positive `delay_seconds`, a prepared
`maximum_delay_seconds`, and feedback in [0, 1). `ModulatedDelay` adds
`base_delay_seconds`, `depth_seconds`, `rate_hz`, waveform, and optional per-channel
phase offsets. Its whole delay span must remain positive and within the prepared
maximum. Delay realizations use bounded linear-interpolated reads, with an
effective minimum of one output frame. Fixed taps use continuous retiming
crossfades over `retime_fade_frames` (default 64); already-retiring reads finish
on their existing deadlines, while a new destination takes the remaining gain.
Preparation reserves `retime_fade_frames + 1` read heads. Modulated reads move
continuously without that crossfade. Parameter actions
are checked against the prepared bounds; decoding or allocating a larger delay
buffer during processing is not part of this contract.

### Oversampled waveshaper

`Waveshaper` replaces `SoftClip` and its `soft_clip` discriminator, without an
alias. Its `curve` is `hard` (clamp to [-1, 1]) or `soft` (tanh). At each
oversample, apply `f(drive*x + bias) - f(bias)`. Positive drive and finite bias
are automatable. Subtracting the bias point preserves zero input at zero while
allowing asymmetric distortion. Apply `10 ** (output_gain_db / 20)` to the wet
output after downsampling; a non-finite represented gain is an error.

Upsample twice by two, apply the curve at four times the input rate, and
downsample twice by two. Each of the four FIRs uses the same 65-tap normalized
half-band coefficients. For tap `n` in 0..64, ideal response is 0.5 at n=32,
zero at other even n, and `sin(pi*(n-32)/2)/(pi*(n-32))` at odd n. Multiply by
the Blackman window `0.42 - 0.5*cos(2*pi*n/64) + 0.08*cos(4*pi*n/64)`, then
normalize the coefficient sum to one. An upsampler inserts a zero after each
sample and multiplies filtered output by two. A downsampler filters every
sample and retains even-indexed outputs. All clocks start at phase zero.

The resulting audio latency is exactly 48 input frames, independent of sample
rate. Delay the dry path by 48 frames too, including while bypassed. Retain four
65-frame histories, their write positions, and a 48-frame dry history per
channel. After its input ends, the processor drains for 96 frames, the finite
support of the FIR cascade. The fixed resource bounds and latency do not change
with curve, drive, bias, output gain, mix or bypass. FIR state stays warm while
bypassed. This mathematical profile does not claim analogue emulation.

`EffectGraph.latencies()` reports each processor's output latency. Align all
incoming audio and end markers to the greatest upstream latency before running
each processor. Delay its resolved controls by that upstream latency too. For a
Waveshaper, additionally delay drive/bias by 24 frames to the nonlinear stage and
mix/bypass/output gain by 48 frames to the output stage. Resolve one control row
per input frame and hold drive/bias through its four oversamples. Initialize
control histories to authored values, with bypass enabled. Snapshots retain all
audio, control and end-marker compensation state.

### Shared-sweep phaser

`Phaser` retains its input layout and runs six identical first-order all-pass
stages. Its instantaneous frequency is
`center_hz * 2 ** (depth_cents * sweep / 1200)`. The nonnegative depth uses the
existing musical-cents unit, accepting values such as `"2 octaves"`; sweep is
in [-1, 1]. Center, depth, sweep, feedback and mix are automatable. Bind sweep
to a shared enveLFO or Patch output for motion; no additional LFO clock is
created inside the processor. The default sweep of zero is static.

At each frame, compute `g = tan(pi * frequency / sample_rate)` and
`a = (g-1)/(g+1)`. Evaluate the frequency in log2 space to avoid an overflowing
intermediate exponent. Resolved frequency must be positive and below Nyquist,
and the represented coefficient must satisfy -1 < a < 1; otherwise fail
explicitly. For each channel, start with
`x = input + feedback * previous_wet`. Set `b = sqrt((1-a)*(1+a))`.
Each of the six stages computes `y = a*x + b*memory`, then
`memory = b*x-a*memory`, using its old memory in both expressions, and passes y
to the next stage. This normalized lattice preserves the stage energy balance
even when a changes every frame. At fixed a, its transfer function is
`(a + z**-1)/(1 + a*z**-1)`.
Store the final y as previous_wet for the next input frame. Feedback is bounded
to [-0.95, 0.95] and always has a one-frame delay.

Mix follows the common linear dry/wet rule, default 0.5; bypass keeps all stage
and feedback state warm. Values below `state_floor` become zero in stage and
feedback memories. After input end, drain until every retained value is below
`tail_threshold`. State floor must be below that threshold. The profile adds
no algorithmic latency: its phase response and internal feedback delay are
intentional DSP behavior. Reserve six stage memories and one feedback value
per channel. Snapshots retain those values and the common controls, lifecycle
and upstream compensation state.

### Compressor and ducker

`Compressor` is a feed-forward, linked peak profile with no look-ahead or added
latency. The `input` port is the dry/output layout. `detector` may have any
nonempty declared layout; its peak at each frame is `max(abs(channel))`. Connect
the main signal to both ports for ordinary compression, or use an external
detector for ducking. It does not mix the detector into the output.

Let `x = 20*log10(peak) - threshold_db`, `r = ratio >= 1`, and `k = knee_db >= 0`.
For nonzero peaks the target gain reduction in decibels is:

```text
x <= -k/2:  0
x >=  k/2:  (1/r - 1) * x
otherwise: (1/r - 1) * (x + k/2)^2 / (2*k)
```

With `k == 0`, use zero below or at threshold and the above-threshold expression
above it. A zero detector peak targets zero reduction. Starting from zero
reduction, update `g = target + exp(-1/(sample_rate*time)) * (g - target)` before
rendering the frame. Use `attack_seconds` when the target is more negative than
the current gain and `release_seconds` otherwise. A zero time means an immediate
update. Times are one-pole time constants, not completion durations.

Multiply every input channel by `10^((g + makeup_db)/20)` before the common
wet/dry interpolation. Defaults are threshold -18 dB, ratio 4, knee 6 dB, attack
10 ms, release 100 ms, and makeup 0 dB. All six parameters are automatable and
can be shared-generator targets. Makeup is explicit; there is no automatic
normalization. Bypass continues advancing detection and reduction. The reduction
scalar is snapshot state. Ending the detector feeds silence and permits gain
recovery; ending the primary input ends this processor's output immediately.
It retains no audio and has no tail. The language-neutral graph and static-knee
examples are in `conformance/compressor.json`.

### Eight-line algorithmic reverb

`Reverb` is a fixed eight-line feedback delay network. Its input is either one
mono channel or named `left`/`right` stereo; its output is always `left`/`right`.
Mono dry audio maps to both outputs with gain `1/sqrt(2)` per channel. Stereo dry
passes through unchanged. The same mapped stereo signal feeds the wet network.
The profile adds no algorithmic latency: its predelay and network echoes are
intentional wet timing, while the dry path stays at its authored frame.

The controls are `predelay_seconds` (default zero), `decay_seconds` (default two),
`damping_hz` (default 6000), and the common `mix` (default 0.25). Predelay must stay
within `maximum_predelay_seconds` (default 0.25); that maximum may be zero.
Predelay uses linear fractional reads including zero-frame delay, with continuous
fixed-tap retiming over `retime_fade_frames` (default 64) and the same bounded
read-head weighting rule as `TapDelay`. Its prepared input history includes the
current frame and the older interpolation neighbor. The maximum, retiming length,
network geometry, tail threshold and state floor are fixed preparation settings.

The eight line lengths in seconds are 0.0297, 0.0371, 0.0411, 0.0437, 0.0531,
0.0617, 0.0713 and 0.0797. `reverb_delay_frames(sample_rate)` rounds these to the
nearest frame with ties to even, retaining at least one frame per line. Each
line is a scalar delay initialized to zero. At frame `n`, read all eight delayed
values `r[i]` before writing their replacements. Wet stereo output uses these
reads with coefficients:

```text
left[i]  = (-1)^(i mod 2) / sqrt(8)
right[i] = (-1)^popcount(i) / sqrt(8)
```

For the feedback path, update each one-pole damping memory before writing:

```text
a = exp(-2*pi*damping_hz/sample_rate)
d[i] = (1-a)*r[i] + a*d_previous[i]
h[i] = d[i] - sum(d)/4
g[i] = 10^(-3*line_frames[i]/(sample_rate*decay_seconds))
```

The Householder feedback matrix is `I - J/4`, where every entry of `J` is one.
Inject predelayed stereo `pL`, `pR` and write:

```text
input_left[i]  = (-1)^floor(i/4) / sqrt(8)
input_right[i] = (-1)^(floor(i/2) mod 2) / sqrt(8)
line_write[i] = input_left[i]*pL + input_right[i]*pR + g[i]*h[i]
```

The input columns and output rows are orthonormal. `decay_seconds` is the nominal
undamped T60; damping shortens high-frequency decay. Coefficients must be
representable with `0 <= a < 1` and `0 <= g[i] < 1`; unsupported floating-point
extremes fail explicitly. Apply the declared `state_floor` to decaying line and
damping state. Bypass keeps processing the wet network. An ended input feeds
silence; drain occurs when predelay history, line histories and damping memories
are all below `tail_threshold`. Stop ends the graph at its exact frame.
Snapshots retain those buffers, write positions, read-head fades and damping
memories. The mono graph and 48 kHz geometry are in `conformance/reverb.json`.

The granulator declares `maximum_duration_seconds`, the fixed output-grain
storage bound. It defaults to the larger of `duration_seconds` and
`history_seconds` and is serialized as a concrete value. The authored duration,
duration actions and the entire duration-modulation domain must remain positive
and at or below this maximum. Raise it explicitly for longer future grains.
Input history and output-grain storage are independent: slow playback can create
an output grain longer than its retained source span. Each native slot reserves
`max(2, round(maximum_duration_seconds * sample_rate))` frames, with ties to even.
The cap is fixed after preparation. Unavailable source footprints still skip
launches under the existing rule; the storage cap does not enlarge input history.

The initial granulator uses a periodic Hann window
`0.5 - 0.5*cos(2*pi*i/N)` for frame `i` of an `N`-frame grain. A grain requires at
least two frames. Duration, playback ratio, source position, and gain are latched
at launch. Gain is `1/sqrt(max(1, density_hz * duration_seconds))`. Before each
output sample the scheduler adds `density_hz/sample_rate` to phase; it launches
one grain and subtracts one when phase reaches one. Density may not exceed the
sample rate. Actions at that frame are applied before the scheduler step.

History uses absolute frame coordinates and linear interpolation. A launch is
skipped unless the complete interpolation footprint is in valid retained input.
Skipped launches still advance scheduler and random state. Jitter uses the
noise-v1 SplitMix64 stream with a processor-instance key. Freeze latches the
valid interval and replays it circularly. For `N` valid frames, let
`X = min(freeze_crossfade_frames, floor((N - 1) / 2))` and `P = N - X`. Map a
requested source position to `q` in `[0, P)` with modulo `P`. At an integer
offset `i < X`, the loop value is the linear blend from frozen frame `P + i` to
frozen frame `i` with weight `i / X`; at other offsets it is frozen frame `i`.
Linearly interpolate between adjacent loop values, wrapping the upper value from
`P` to zero. Thus a full history uses `freeze_crossfade_frames` (default 64), while a
startup freeze uses only available recorded frames and never exposes initialized
but unavailable storage. Implementors must retain samples used by active grains
across unfreeze without allocation.

## Actions and timing

Prepared parameter, bypass, freeze, input-end, and stop actions use absolute
integer frames and ordinals. `ActionBatch` contains every effect action produced
by one event at one frame; its ordinals strictly increase. Admission accepts or
rejects the entire batch. Parameter actions ramp linearly for their declared
frame duration. Actions apply before processing their frame. Processor parameters
are addressed by graph-local processor ID and parameter ID.

The live transport has fixed capacities for batches, actions per batch, and
actions per frame. Hosts publish ordered whole batches with scheduling lead;
offline rendering uses the same executor after admission. Late controls are
discarded and reported. A late lifecycle batch requires stream resynchronization.
Stop uses a separate bounded path. These transport rules do not relax offline
validation.

Each graph input ends independently. A node specifies which inputs govern its
lifetime and reports the exact first frame after its output. End markers and
controls receive the same latency compensation as audio. Temporary silence does
not end an instrument or master stream. Graphs cannot restart after output end
without reset.

Snapshots include processor state, input-end state, compensation buffers,
internally delayed actions, active grains, random state, and capacity reservations.
Unconsumed transport batches return to the caller before snapshot and are
resubmitted after restore. The graph/asset digest and capacities must match.

Granular position jitter uses the launch counter as a SplitMix64 input. Add the
golden-ratio increment, apply the standard two xor-shift/multiply mixes and final
xor shift with wrapping unsigned 64-bit arithmetic, then convert the upper 53
bits to `[0, 1)` and linearly map that value to `[-1, 1)`. The counter advances
for every scheduled launch, including launches skipped for unavailable history
or a full grain pool.

## One-pole highpass and DC removal

`Highpass` preserves its input layout, defaults to 20 Hz, and has unity gain at
Nyquist. It has zero initial state and zero algorithmic latency. Cutoff must
remain positive and strictly below Nyquist, including resolved automation.
There is no implicit clamp. `cutoff_hz` uses hertz and accepts generator routes.

Let `g = tan(pi*cutoff_hz/sample_rate)`, `a = (g-1)/(g+1)` and
`b = sqrt((1-a)*(1+a))`. For each channel and frame, use the old memory `s`:
`allpass = a*x+b*s`, `s_new = b*x-a*s`, `highpass = (x-allpass)/2`.
This normalized lattice retains an energy balance under cutoff modulation.
At fixed cutoff its response is `(1-a)/2*(1-z^-1)/(1+a*z^-1)`.
Retained state below `state_floor` becomes zero; after input end, drain until
all channel memories are below `tail_threshold`. Bypass keeps state warm.

## Always-applied channel routing

`ChannelMatrix` declares ordered `input_channels`, `output_channels`, and one
coefficient row per output channel. Every row has one coefficient per input.
The input layout must match its source exactly; channel names are unique within
each layout. Coefficients are finite linear gains. There is no implicit
normalization, clipping, wet/dry control, bypass or coefficient automation.
Parameter, bypass and freeze actions are rejected for routing matrices.

An output sample is the compensated sum of its coefficient/input products,
matching scalar `fsum` behavior under cancellation. Non-finite products or
unrepresentable sums fail explicitly. Storage is fixed by the authored matrix.
The routing is stateless, has zero added latency and ends with its input.

The Python preset functions produce ordinary `ChannelMatrix` definitions:
`polarity_matrix` negates each declared channel; `pan_matrix` maps named `mono`
to `left/right` using cosine/sine equal-power gains for pan in [-1, 1];
`balance_matrix` attenuates the opposite stereo side without boosting either
side; `width_matrix` scales side by width in [0, 2], leaving mid unchanged;
`mid_side_matrix` encodes or decodes with `(L+R)/sqrt(2)` and `(L-R)/sqrt(2)`.
Swap, unnormalized sum/difference and arbitrary channel mapping use explicit
coefficient rows, as illustrated in `conformance/channel-matrix.json`.

## Named mixers and crossfaders

`Mixer` declares its ordered input ports through `MixerInput` entries. Every
port has a unique name, a decibel gain, mute and solo selectors. All input
layouts must match exactly. No wet/dry or bypass control is added. Inputs are
summed with compensated accumulation, without normalization or clipping.

If any input is soloed, only soloed inputs are eligible. Mute still silences a
soloed input. Initial gate gains are the authored eligibility values, without
startup fades. Selector changes target eligible gates at one and others at
zero. A changed target starts a linear amplitude fade from the current gate
over `switch_fade_frames` (default 64). The request frame uses the old gain;
the target is reached after that many frames. Another changed target retimes
continuously from the current value; duplicate selectors do not restart a fade.

Parameter names are `<port>-gain_db`, `<port>-muted` and `<port>-solo`. Gains
accept ordinary ramps and generator routes. Selector actions use exactly zero
or one with zero `duration_frames`; the mixer supplies their internal fades.
Selectors are not continuous modulation targets. Ending an input makes it zero
without changing gain/mute/solo selection. The mixer ends only after every
aligned input ends; no implicit reweighting occurs.

`Crossfader` has named `first` and `second` ports with identical layouts and an
automatable position in [0, 1]. Its law is required explicitly. Linear weights
are `1-position, position`; equal-power weights are cosine/sine of
`pi*position/2`. Endpoint weights are exactly zero/one. Equal-power center
can boost correlated inputs. There is no additional wet/dry or bypass control,
normalization or clipping. It ends after both aligned inputs end.

Both profiles preserve input channels and add zero algorithmic latency. All
authored ports determine fixed prepared storage. Audio, controls and input-end
markers retain shared upstream latency compensation; stop is immediate.

## Audio-derived envelope followers

`Follower` is an analysis processor with one `input` audio port. It has no
audio output, wet/dry or bypass control. A dedicated binding
`{kind: "follower", name: "amplitude", processor: "level"}` exposes its
linear-amplitude observation to effect modulation. Follower bindings are
rejected in synth/sample modulation settings. A follower cannot feed an audio
port or be the graph's audio output. Every follower must contribute through a
control route to the graph output, directly or through other processors.

For each frame, peak is the maximum absolute input sample across channels.
Initially level is zero. Select `attack_seconds` when peak exceeds level,
otherwise `release_seconds`. Defaults are 0.01 and 0.1 seconds respectively;
both accept nonnegative ramps and modulation. With a zero duration, level
becomes peak immediately. Otherwise update
`level += (peak-level) * (1-exp(-1/(sample_rate*seconds)))`.
The newly updated level is available to downstream control routes in that
same frame. Retained level below `state_floor` (default 1e-30) becomes zero.
Input end supplies zero peak; release continues until level is below
`tail_threshold` (default 1e-12), then level becomes zero and analysis ends.
State floor must be strictly below tail threshold. Stop is immediate.

The source uses voice scope for one graph instance, with minimum zero and an
explicit authored maximum. Output is raw amplitude, without normalization or
clamping; it can exceed one. Observations beyond the authored source domain
fail under the ordinary modulation contract. Route mapping remains explicit.

Follower routes add directed processor dependencies. Self-dependencies and
combined audio/control cycles are rejected. Preparation orders each analysis
before its consumers. A consumer's arrival latency is the maximum of all its
audio and control-source latencies; earlier paths are delayed to match it.
Authored parameter actions and generator observations use that same arrival
time. Processor-specific internal control compensation still applies, such as
the oversampled Waveshaper's drive/bias and output-gain delays. Alignment and
follower level are retained in snapshots. End markers follow the aligned
dependencies, so a consumer ends only after its required paths have ended and
its own tail has drained. The conformance example is `conformance/follower.json`.

## Zero-look-ahead gate and downward expander

`Gate` and `Expander` have explicit `input` and `detector` audio ports.
Their detector is the maximum absolute sample across detector channels. The
detector may use the program source or a separate sidechain, with any declared
channel width. One gain applies to all program channels; the program's named
layout is preserved. Both add zero algorithmic latency and use common mix,
warm bypass, upstream compensation and immediate-stop rules. Ending the
detector supplies silence without ending the program. Neither stores audio:
an ended, aligned program has no independent dynamics tail.

Defaults are threshold -40 dB, attack 0.001 seconds and release 0.05 seconds.
The gate additionally defaults to 6 dB hysteresis and 0.01 seconds hold. It
starts closed at zero gain. It opens at or above threshold. While open, it
counts consecutive frames strictly below threshold minus hysteresis. Hold is
`ceil(hold_seconds*sample_rate)` frames: that many low frames remain open,
then the next low frame closes it. Zero hold closes on the first low frame.
Returning to or above the closing threshold resets elapsed hold. The count
is compared against the current hold setting every frame, so shortening an
active hold can close the gate immediately; lengthening it extends the wait.
Reopening requires reaching the opening threshold. Target gain is one when
open and zero when closed.

The expander starts at unity gain and defaults to a 2:1 ratio. It has a hard
knee. With detector level `L` dB below threshold `T`, target gain is
`10**(((ratio-1)*(L-T))/20)`. At or above threshold it is one. Ratio one is
unity, including at silence; otherwise silence targets zero gain. Negative
infinite attenuation is permitted to underflow to zero. Gain never exceeds one.

Both smooth linear gain toward its target using attack when target gain is
higher and release otherwise: `gain += (target-gain)*(1-exp(-1/(rate*seconds)))`.
Zero time applies the target immediately. The updated gain multiplies that
frame's program audio. Threshold, attack/release, gate hysteresis/hold and
expander ratio accept actions and modulation. Hold counts use integer frames;
JSON/native snapshots retain gain, gate state and elapsed hold in addition
to shared graph state. The conformance example is `conformance/gate-expander.json`.

## Multitap authoring composition

`multitap_graph` accepts named `DelayTap` definitions and expands them into
ordinary `TapDelay`, `ChannelMatrix` and `Mixer` processors. Each tap declares a
positive delay and maximum delay, gain in dB (default -6), and static pan/balance
in [-1, 1] (default center). Tap names are unique and at least one is required.
The input is mono with any declared name, or named left/right stereo; output is
named left/right stereo. Mono uses equal-power panning, including a centered
dry path. Stereo uses attenuation-only balance and preserves centered dry.
Dry gain defaults to 0 dB. There is no implicit clipping or normalization.

For graph name `echo` and tap `first`, node IDs are `echo-tap-first` for the
delay and `echo-pan-first` for placement. `echo-dry` places the dry input;
`echo` is the mixer with ports `dry` and `tap-first` (and one such port per tap).
Delay retiming targets `echo-tap-first.delay_seconds`; gain targets
`echo.tap-first-gain_db`. Mixer mute/solo and gain ramps retain their ordinary
contracts. Placement is static. Each tap has zero feedback and independent
bounded delay/retiming storage. Musical delay adds no algorithmic latency, so
the dry path is not compensated to the echo time. The mixer ends after every
input tail has drained.

The emitted graph is the portable definition and can be extended with ordinary
modulation, actions or routing. It uses the standard scope/owner and prepared
block limits, without another DSP or snapshot type. The conformance authoring
example is `conformance/multitap.json`.

## Optional feedback damping

`TapDelay.damping_hz` defaults to `None`, selecting the existing undamped loop.
A positive frequency prepares one initially zero normalized all-pass memory per
input channel. It is a one-pole low-pass with unity DC gain and zero gain at
Nyquist: `g=tan(pi*cutoff/rate)`, `a=(g-1)/(g+1)`, `b=sqrt((1-a)*(1+a))`;
using old memory `s`, `allpass=a*x+b*s`, `s_next=b*x-a*s`,
`filtered=(x+allpass)/2`.

Each frame reads and mixes its existing delay heads, filters that delayed value,
multiplies the filtered value by feedback gain, and adds it to the new input
before writing history. The audible delayed read remains unfiltered, so later
repeats become progressively darker. Damping adds no algorithmic latency and
does not change interpolation or retiming. Bypass keeps the complete loop warm.

Prepared damping accepts positive cutoff actions and modulation. Cutoff must
remain strictly below Nyquist with a representable coefficient in (-1, 1);
renderers reject unsupported values without clamping. Disabled damping cannot
be enabled by an action: it requires preparing another definition. State below
`state_floor` becomes zero; after input end both delay history and damping
memories must fall below `tail_threshold` before retirement. Snapshots retain
damping memory and its enabled/disabled preparation identity. The conformance
example is `conformance/feedback-damping.json`.

## Failure and real-time boundary

Preparation and submission reject detectable errors outside processing. Native
processing performs no allocation, deallocation, Python calls, blocking locks,
file access, decoding, or logging. Fatal processing failure zeros the entire
caller block, records the first processor/frame in bounded status storage, and
latches the graph failed until reset. Successful blocks are partition-independent;
the discarded block after failure follows the host block boundary.

State trimming is not a complete defense against subnormal operands or results.
Native implementations must benchmark tiny inputs and long decays on each target
before choosing a scoped thread-local floating-point mode.

### Matrix feedback delay

`MatrixDelay` uses the same bounded fixed-delay settings and controls as
`TapDelay`, with one delay time shared by all channels. It preserves its input's
named channel layout. Its required static `feedback_matrix` is square and must
match that channel count. Rows are destinations and columns are sources; signed
finite coefficients are accepted unchanged, and each row's absolute sum must be
at most one. The separate `feedback` gain remains in `[0, 1)`.

For every frame, read all delayed channels, optionally low-pass them using the
shared damping profile, multiply that vector by the feedback matrix, then apply
`feedback` and add the current input before writing the history. The audible wet
read remains unfiltered. All channel writes use the same pre-write vector, so
cross-feedback has no channel-order dependency. For stereo, `[[0, 1], [1, 0]]`
swaps feedback channels and makes successive echoes alternate sides when the
initial input occupies one side. An identity matrix has TapDelay semantics.
Coefficients are static and have no automation target; delay time, damping,
feedback, mix and bypass retain their existing controls and tail rules.

`conformance/matrix-delay.json` provides a damped stereo ping-pong definition.

### Doubling, ensemble and ADT composition

`modulated_multitap_graph` takes authored `ModulatedTap` voices and returns an
ordinary effect graph using ModulatedDelay, ChannelMatrix and Mixer nodes. Each
voice holds an existing `ModulatedDelay` in `delay`, plus `gain_db` and `pan`.
The delay's name identifies the voice. All of its bounded timing, waveform,
per-channel phase, feedback, mix and tail settings remain explicit. The helper
uses the same mono equal-power pan, stereo attenuation-only balance, dry mapping,
layout restrictions and dry-gain convention as `multitap_graph`.

For graph `ensemble` and voice `one`, the delay node is `ensemble-tap-one`, its
placement node is `ensemble-pan-one`, and the mixer input is `tap-one`.
The mixer is named `ensemble`. Delay base/depth/rate/feedback and mixer gain,
mute/solo remain ordinary graph targets. Standard shared enveLFO bindings can
replace periodic motion by setting internal depth to zero and routing to the
voice's base delay; preparation still checks the declared delay span.

The authored voice count and each maximum delay fix storage. Initial phases
and rates are explicit and deterministic; this profile uses no random drift or
tape-transport clock. Snapshots and endings use existing processors only.
Musical delay adds no graph alignment latency. There is no gain normalization
or clipping. `conformance/modulated-multitap.json` gives named mono-input recipes:
two wet voices for doubling, four for ensemble, and one wet voice alongside the
dry signal for ADT. Their phases, rates and placement decorrelate the reads;
they are authored recipes rather than additional DSP processor kinds.
