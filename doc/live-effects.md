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
