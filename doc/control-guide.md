# Choosing a control representation

Motion event connections, including internal Patch connections, accept `every`
as a positive integer (default `1`) and `offset` as a nonnegative integer (default
`0`). Each connection skips `offset` matching events initially, then forwards
every nth matching event. For `every = 3`, offsets 0, 1, and 2 forward 1, 4, 7;
2, 5, 8; and 3, 6, 9, respectively. Offsets may exceed `every`: offset 4 starts
at event 5, not event 2. Nonmatching
ports do not advance the count. Counts belong to each connection and voice,
reset on voice activation, and survive snapshots; stage transitions, contour
restarts, and render-block boundaries do not reset them. Division filters
delivery, not the source Motion's emitted events or named event outputs.

`probability` (default `1`) gates events selected by `every` and `offset`.
Zero blocks all selected events; one forwards all. Intermediate cutoffs draw once per
selected event, independently per connection and voice, without changing the
divider count. Prepared starts carry `motion_key`, derived from the trace seed
and voice ID with domain-separated SHA-256. Connection streams combine it with
the target Motion identity and authored connection position. SplitMix64 words
use their high 53 bits and compare against `floor(probability * 2**53)`.
Cutoffs zero and 2**53 consume no random words, including probabilities too
small to produce a nonzero cutoff. Snapshots retain random state; voice
activation initializes it, while child restarts and stage changes retain it.
Reproducing the seed, voice identities, and connection order reproduces the
pattern independently of render partitioning and voice-slot allocation.

`delay` is a nonnegative rational number of seconds (default `0`), applied
after division and probability gating. A forwarded command is delivered once at
the source event time plus its delay, without testing its gates again. Pending
commands belong to the voice, survive snapshots, and remain active during its
release tail. Stopping or retiring that voice discards them. enge permits at most
4096 pending delayed commands per voice and reports overflow instead of dropping
events. Zero delay retains immediate delivery.

Choose by what drives the value and who owns its lifetime. These models describe
different operations; none is a replacement for all the others.

| Model | Driver and clock | Lifetime and boundaries | Units and owner |
| --- | --- | --- | --- |
| `automation.TimelineCurve` | A start tick, initial value, and segments in its score timebase | Inactive before its start; holds the final value afterward; `hold`, linear, or equal-power interpolation | Declared unit; combines through its containing `Automation`, with a target, scope, default and explicit writer operations |
| `envelope.Curve` | Elapsed rational seconds from activation | Runs autonomously; holds its final level or repeats its positive-length period | General scalar, including unbounded gain; caller owns activation |
| `envelope.Envelope` | Trigger/release events on rational seconds or beats | Trigger segments, optional hold, then release from the current level; explicit retrigger policy | Unipolar or bipolar normalized signal, with declared instrument/part/voice scope |
| `lfo.LFO` | Elapsed seconds or beats and ordered rate/reset events | Repeats waveform; reset policy controls phase, and phase integrates the event history | Normalized waveform with declared scope; host supplies the clock |
| `modulation.Route` | Current source value, not its own clock | Maps a source through an optional table and combines at a target; no independent activation or gate | Source and target domains, units and scopes are validated by the containing modulation model |
| `binding.ParameterMapping` | A canonical parameter value supplied to an adapter | Stateless conversion; explicit reject/clamp policy; piecewise tables cover input endpoints, enum maps list allowed values | Converts declared canonical units to native adapter values; does not schedule updates itself |
| `samples.controls.ControlState` | Ordered target events on rational seconds | Finite linear smoothing with interruption from the current value; zero duration steps immediately | Declared control source domain, before modulation mapping; one state per context/control/smoothing duration |

Automation `hold` and route interpolation `step` both retain a preceding value
between points, but their axes differ: timeline ticks versus current source
values. They remain distinct enums because the available modes and enclosing
contracts differ. Envelopes use segment curvature instead of either enum.

An ordinary pattern is an envelope or LFO producing a normalized signal, a route
applying it to a frequency/gain parameter, and a binding converting that canonical
value to an adapter's native representation. Timeline automation can instead
supply an explicitly authored parameter history. Declare multiple writers and
their combination operations explicitly; do not infer precedence from file order.

Scalar evaluators work on validated inputs. Event-driven envelope/LFO state can
be replayed using its own API; instrument snapshots are observations and do not
provide a resumable player. See [validation](validation.md) and
[capabilities](capabilities.md) for those boundaries.

[Instrument control evolution](control-evolution.md) defines source smoothing,
prepared trigger contexts, and how resolved pitch combines with live tuning.
Scalar control state is resumable independently of observational instrument
snapshots; it does not by itself restore the whole instrument.
