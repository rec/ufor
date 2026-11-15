# Prepared tremolo and vibrato profiles

`tremolo_graph` and `vibrato_graph` author ordinary EffectGraph definitions. Both
use one seconds-clock, voice-scoped shared enveLFO sine generator per instance,
named `<name>-motion`. Rate, depth and phase are preparation settings. Phase is
in cycles [0,1), rate is finite and nonnegative in Hz, and rate zero holds the
initial phase. Channels share one motion signal and retain their names.

Tremolo composes a same-layout zero ChannelMatrix `<name>-silence` and a linear
Crossfader `<name>` with silence first and original audio second. Its position
is 1-depth/2 plus a sine contribution of depth/2, so amplitude is:

    gain(t) = 1 - depth/2 + (depth/2) * sin(2*pi*(rate*t + phase))

Depth is in [0,1], with zero giving unity and one reaching silence. There is no
boost or level normalization. Defaults are depth 0.5, rate 5 Hz and phase 0.25,
which starts at unity. There is no intrinsic latency or tail. These always-applied
routing nodes have no internal bypass; compose a separate dry blend if required.

Vibrato composes one fully wet ModulatedDelay `<name>`, with feedback zero,
internal oscillator depth zero, and a shared sine route to base_delay_seconds:

    delay(t) = base_delay_seconds + depth_seconds * sin(2*pi*(rate*t + phase))

Defaults are base 5 ms, depth 0.5 ms, maximum storage 10 ms, rate 5 Hz, phase 0.
Require a positive minimum delay and base+depth no greater than the maximum.
Reads use the existing one-frame minimum and linear fractional interpolation.
This is delay-time depth, not an exact symmetric cents specification; pitch
excursion depends on both depth and rate. Extreme settings retain the existing
moving-delay behavior. Depth zero retains the delay bias. This is musical delay,
not intrinsic alignment latency, so graph latency remains zero. Input end drains
the bounded history; ordinary warm bypass/mix retain their existing meanings.

Generators start at graph frame zero, continue through bypass and tails, and
use existing portable and opaque snapshot state. Stop ends immediately. Direct
actions on the expanded processors remain ordinary graph actions; these helpers
do not add named live rate/depth controls or a second oscillator implementation.

See `conformance/vibrato-tremolo.json` for the selected default recipes. Expanded
graphs round-trip through the ordinary portable graph model.
