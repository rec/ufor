# White noise synthesis

`NoiseVoice` shares synth mapping, lifecycle, envelope, processing, and channels.
Its required `noise: "white"` field distinguishes it from `oscillator` and `fm`
sources. Set mapping `pitch_tracking: false`; reference pitch is optional and
unused. Keys still select notes and modulation sources. Frequency offsets,
processing tuning, and tuning modulation are rejected. Event pitch does not
alter the noise stream. Amplitude and filter cutoff/Q use the existing targets.

The mono source passes through ordered processing filters, then its amplitude
envelope and gain, then channel routes. Minimum hold, sustain, release, stop,
and completion follow oscillator lifecycle semantics; completion discards filter
state. Zero gain does not pause generation. Other colors are not defined.

## noise-v1 stream contract

The sole performance seed is the unsigned 64-bit `synth_trace.prepare` seed.
Each noise `VoiceStart` carries an unsigned 64-bit `noise_key`, required only for
noise starts. Derive it as the first eight SHA-256 digest bytes, interpreted
big-endian, of these concatenated bytes:

1. ASCII `ufor-noise-v1` followed by a zero byte.
2. The seed as exactly eight unsigned big-endian bytes.
3. The canonical voice ID encoded as UTF-8, without a terminator.

`ufor.noise.stream_key` implements this portable derivation. Voice identity is
assigned by the existing ordered lifecycle preparer. Other source actions omit
the noise key. Passing just prepared actions retains all source randomness.
This is reproducible decorrelation, not a guarantee that 64-bit keys never collide.

## Numerical definition

Use the fixed-increment [SplitMix64 algorithm](https://prng.di.unimi.it/splitmix64.c)
with random access by zero-based voice sample index `n` and resolved key `k`.
All arithmetic below is unsigned 64-bit with wrapping multiplication/addition;
shifts are logical:

```text
z = k + (n + 1) * 0x9e3779b97f4a7c15
z = (z XOR (z >> 30)) * 0xbf58476d1ce4e5b9
z = (z XOR (z >> 27)) * 0x94d049bb133111eb
word = z XOR (z >> 31)
x[n] = 2 * (float64(word >> 11) / 2**53) - 1
```

The mapping produces values in `[-1, 1)` exactly representable as float64. For
key zero, the first four words in hexadecimal are `e220a8397b1dcdaf`,
`6e789e6aa1b965f4`, `06c45d188009454f`, and `f88bb8a8724c81ec`.
The language-neutral vectors in `conformance/noise-v1.json` include additional
keys, high indices, stream derivation, and scalar values.

The next sample index is an integer in `[0, 2**64]`; `2**64` is the exhausted
sentinel. A positive render that would cross exhaustion fails before state is
changed. Every active frame consumes one word, including muted frames and
release tails. Zero frames consume none. Ended voices consume none. Block size,
rendering order between voices, and parameter changes do not alter the stream.
No normalization, clipping, or DC correction is implicit. These streams are
for audio, not cryptographic use.

Snapshots retain key/index exactly, plus envelope, filters, controls, and voice
lifecycle state. Integer agreement is exact; processed audio uses declared
floating tolerances. enge owns DSP implementations and backend identity.
