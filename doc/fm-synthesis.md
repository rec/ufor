# Graph FM profile

FM voices use `SynthInstrumentScore`, the existing synth performance preparer,
and shared lifecycle actions. A voice has `fm` instead of `oscillator`; its
prepared start carries FM settings and a null oscillator. This is a distinct
source definition, not a new oscillator waveform. Mixed source scores are
portable; an engine may reject unsupported source profiles during preparation.

`FM.operators` contains two through six uniquely named operators. An operator's
latched `waveform` is `sine` by default. At phase `p` in [0, 1), sine is
`sin(2*pi*p)`; square is +1 for `p < 1/2` and -1 otherwise; triangle is
`4*p - 1` for `p < 1/2` and `3 - 4*p` otherwise. These are output values before
the operator envelope. `edges`
carry nonnegative phase-modulation indices from a source operator to a
destination operator. An edge with `delayed: true` reads its source output from
the preceding sample; all other edges read the current sample and must form an
acyclic graph. `carrier` names the one audible operator. Carrier level is a
nonnegative linear gain. Operator ratios are positive, tuning is in cents, and
initial phases are cycles in [0, 1).

At output frame n, render before advancing each phase. The following equations
describe the operator graph and its carrier output before downstream processing:

```
offset_radians_i[n] = sum(current_edge_index[n] * output_source[n])
                     + sum(delayed_edge_index[n] * output_source[n-1])
output_i[n] = envelope_i[n] * waveform_i(
                (phase_i[n] + offset_radians_i[n] / (2*pi)) modulo 1)
c[n] = carrier_level[n] * output_carrier[n]
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

Each operator declares a shared unipolar `Envelope`. Renderer preparation must
check which clocks, shapes, playback modes, and commands it supports; the Ufor
operator model does not restrict every envelope to a held linear seconds profile.
All receive the same effective release after minimum hold. The carrier's release
completion ends the voice, even if another operator has a longer tail. A completed
operator contributes zero. Immediate stop discards all operators. No separate
voice amplitude envelope is allowed. Modulator envelopes remain part of graph
evaluation. The carrier's audible envelope and processing gain follow
`processing.filter_order`: before-amplitude filters process the raw carrier
before that amplitude stage; after-amplitude filters process the shaped carrier.
The envelope-scaled operator values used by graph edges are unchanged by this
audible-path ordering. Channel routing follows processing.

Modulation addresses are `operator-NAME.ratio` (ratio),
`operator-NAME.tuning_cents` (cents), `edge-NAME.index` (radians), and
`fm.carrier_level` (ratio), alongside existing processing/filter addresses. An
unnamed edge uses `SOURCE-DESTINATION` as its name; explicit edge names are only
required when those derived names would collide. Declared defaults must match
authored settings. Ratio domains are positive; indices and levels are
nonnegative. All synth targets remain voice-scoped. Reuse existing source
bindings, smoothing, and domain errors.

Controls take effect before their addressed sample; pitch/ratio changes preserve
phase. Topology, phases, and envelope definitions are latched at trigger time.
Audio snapshots must retain both phases and accumulation corrections, delayed
feedback, operator envelope/release state, and the usual controls and filters.

Yamaha DX7 and TX81Z templates preserve dedicated patch bytes and envelope
semantics instead of being converted implicitly to this graph. See
[Yamaha voice templates](sample-performance.md#yamaha-synth-voice-templates).

DX7 topology uses a `DX7Edge` for `DX7Algorithm.feedback`, with an explicit
source and destination in visible operator numbering. Ordinary feedback loops
have equal endpoints. Algorithm 4 returns operator 4 to operator 6; algorithm 6
returns operator 5 to operator 6. These delayed edges remain separate from the
feed-forward `edges` list. This replaces the former single-operator integer;
lossless VCED and packed voice bytes are unchanged. Feedback strength and delay
arithmetic remain renderer responsibilities.
