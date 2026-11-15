# Dynamic EQ

`DynamicEQ` is one normalized band-pass bell with linked peak-driven downward
dynamics. It preserves named channels, has one `input` port, and declares zero
frame latency. Compose multiple nodes for multiple bands. It has ordinary mix,
warm bypass and scoped controls; there is no external detector or dynamic boost.

The band uses the existing one-stage normalized trapezoidal resonant filter,
with center frequency and Q, zero initial integrators, and unity band-pass gain
at its center. Reuse its 1 Hz minimum and 0.999 Nyquist-ratio bounds. Frequency
and Q accept per-frame actions, ramps and scoped modulation. Retain integrator
state across coefficient changes, including jumps. No filter-instance crossfade
is implied; sudden tuning changes can produce transients. Recompute coefficients
when their exact effective inputs change.

For band-pass output b[n,c], the linked detector is max_c(abs(b[n,c])). Compute
the existing Compressor soft-knee target reduction in dB, then cap that target
at -maximum_cut_db before applying its attack/release recurrence. Reduction starts
at zero. Lowering maximum_cut_db releases existing reduction toward the new target
with the current release time; it is a target limit, not an immediate state clamp.
There is no makeup. With g[n] = 10^(reduction[n]/20), fully wet output is:

    y[n,c] = x[n,c] + (g[n] - 1) * b[n,c]

For constant g this is a bell cut: center gain g, and unity far from the band.
At g=1 the original samples pass through exactly. "Cut-only" constrains this
gain coefficient; it does not impose a sample-peak ceiling on transients or
rapidly modulated filters.

Defaults are 1 kHz, Q 1, -18 dB threshold, ratio 1, knee 6 dB, attack 10 ms,
release 100 ms, maximum cut 12 dB and mix 1. Ratio 1 is neutral. Center, Q,
threshold, ratio, knee, attack, release, maximum cut and mix accept parameter
actions and modulation. Fixed state_floor/tail_threshold follow existing filters.
After input end, feed zeros through the band until every integrator falls below
tail_threshold; gain reduction alone does not extend the audio tail. Stop ends
immediately. Snapshots retain the two integrators per channel and reduction in dB.

See `conformance/dynamic-eq.json` for a portable definition.
