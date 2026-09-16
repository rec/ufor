# Choosing a control representation

Choose by what drives the value and who owns its lifetime. These models describe
different operations; none is a replacement for all the others.

| Model | Driver and clock | Lifetime and boundaries | Units and owner |
| --- | --- | --- | --- |
| `automation.TimelineCurve` | Knots at strict integer ticks in its score timebase | Inactive before the first knot; holds the last value afterward; `hold`, linear, or equal-power interpolation | Declared unit; combines through its containing `Automation`, with a target, scope, default and explicit writer operations |
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
