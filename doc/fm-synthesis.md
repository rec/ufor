# Two-operator FM profile

FM voices use `SynthInstrumentScore`, the existing synth performance preparer,
and shared lifecycle actions. A voice has `fm` instead of `oscillator`; its
prepared start carries FM settings and a null oscillator. This is a distinct
source definition, not a new oscillator waveform. Mixed source scores are
portable; an engine may reject unsupported source profiles during preparation.

`FM.operators` contains two uniquely named sine operators. `connection.source`
names the modulator and `connection.destination` the audible carrier. The
connection index and modulator self-feedback are nonnegative radians. Carrier
level is a nonnegative linear gain. Operator ratios are positive, tuning is in
cents, and initial phases are cycles in [0, 1).

At output frame n, render before advancing either phase:

```
m[n] = envelope_m[n] * sin(2*pi*phase_m[n] + feedback[n]*m[n-1])
c[n] = carrier_level[n]*envelope_c[n] * sin(2*pi*phase_c[n] + index[n]*m[n])
frequency_i[n] = prepared_pitch_hz * ratio_i[n]
                 * 2**((processing_tuning[n] + operator_tuning_i[n])/1200)
phase_i[n+1] = (phase_i[n] + frequency_i[n]/sample_rate) modulo 1
```

`prepared_pitch_hz` already includes the voice's static frequency offset, once,
under the existing synth preparation rule. Initial feedback history is zero.
Feedback uses the previous output sample's envelope-scaled modulator value.
Index modulation changes phase deviation, not instantaneous frequency deviation.
The profile renders at output rate and permits aliasing; no implicit clipping,
normalization, oversampling, phase reset, or smoothing is specified.

Each operator uses a held linear unipolar voice envelope on the seconds clock.
Both receive the same effective release after minimum hold. The carrier's release
completion ends the voice, even if the modulator has a longer tail. A completed
modulator contributes zero. Immediate stop discards both operators. No separate
voice amplitude envelope is allowed. Apply carrier envelope/level, then ordered
voice filters, then processing amplitude/gain and channel routing.

Modulation addresses are `operator-NAME.ratio` (ratio),
`operator-NAME.tuning_cents` (cents), `fm.index` and `fm.feedback` (radians), and
`fm.carrier_level` (ratio), alongside existing processing/filter addresses.
Declared defaults must match authored settings. Ratio domains are positive;
index, feedback, and level domains are nonnegative. All synth targets remain
voice-scoped. Reuse existing source bindings, smoothing, and domain errors.

Controls take effect before their addressed sample; pitch/ratio changes preserve
phase. Topology, phases, and envelope definitions are latched at trigger time.
Audio snapshots must retain both phases and accumulation corrections, delayed
feedback, operator envelope/release state, and the usual controls and filters.
