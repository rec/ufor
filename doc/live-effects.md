# Portable live-effect graphs

uFor defines fixed acyclic processor graphs for offline and live audio effects.
enge owns their numerical realization. A graph belongs to a voice, instrument,
master, or host attachment and has named audio inputs, processor nodes, explicit
connections, and one public output. Serial chains normalize into this graph form.

Every processor has a stable local ID. Audio input ports are fixed by processor
type and are distinct from scalar modulation. Gain, resonant filter, and
granulator processors have `input`; multiplication has equal-layout `carrier`
and `modulator` ports. Connections may fan out, but a port has one source and
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

All processors preserve the primary input layout in this profile. Multiplication
requires identical carrier and modulator layouts and multiplies corresponding
samples. Wet/dry uses the designated dry input and linear interpolation:

```text
output = (1 - mix) * aligned_dry + mix * wet
```

Bypass ramps toward dry over 64 frames while processing and state advancement
continue. Authored mix remains independent, so unbypass returns to its current
value. Retiring a tail also uses a 64-frame linear fade. Processor-mode resonant
filters use the existing filter definitions, a `1e-12` tail threshold, and may
trim only their designated decaying integrator state below `1e-30`. These values
are portable profile constants, not host preferences.

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
`P` to zero. Thus a full history uses the declared 64-frame overlap, while a
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
