# Three-band compression

`MultibandCompressor` preserves named channels and has one `input` port. It is
always wet, with no mix, bypass or freeze action. Compose dry paths explicitly.
There is no look-ahead or frame latency; the crossover changes phase.

Prepare two strictly increasing crossover frequencies below Nyquist (defaults
200 Hz and 4 kHz). Each LR4 branch cascades two Butterworth second-order sections,
Q = 1/sqrt(2), with bilinear prewarping. Split at the lower crossover, then split
its upper branch at the upper crossover. Pass the low band through a second-order
allpass at the upper crossover, with the same Butterworth denominator. Its
numerator reverses the denominator coefficients. Thus the neutral sum is the
product of the two second-order allpasses and has unity magnitude.

Each band independently links the absolute peak over its named channels, then
uses the existing soft-knee Compressor reduction-in-dB recurrence, including
attack/release, makeup and zero-time behavior. `low`, `mid`, `high` are
CompressorBand settings. Defaults are neutral: ratio 1 and makeup 0. Controls are
`low-threshold_db`, `mid-ratio`, `high-attack_seconds`, etc. All six dynamics
settings accept ordinary parameter ramps and scoped modulation. Crossover
frequencies are fixed, and there is no external detector port.

Filter integrators start at zero and snap below state_floor after each section
update. Continue zero-input processing after input end until all crossover
integrators are below tail_threshold, then output zero and mark drained. Gain
reduction state alone does not extend an audio tail. Snapshots retain nine
second-order sections (two integrators per channel) and three reduction values.
Non-finite controls, state or output fail explicitly. Storage depends only on
the prepared channel count, with plans and coefficients prepared before rendering.

See `conformance/multiband-compressor.json` for a portable definition.
