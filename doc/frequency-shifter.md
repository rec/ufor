# Frequency shifter

`FrequencyShifter` preserves named channels independently and adds 512 frames of
intrinsic latency. Its fixed 1,025-tap Hilbert FIR uses a Blackman window:

    h[n] = 2 / (pi * (n-512)) *
           (0.42 - 0.5*cos(2*pi*n/1024) + 0.08*cos(4*pi*n/1024))

Odd n use this expression; even n are exactly zero. No normalization is applied.
The real branch is x[t-512]; the quadrature branch is sum(h[n]*x[t-n]).
The wet output is real*cos(2*pi*phase) - quadrature*sin(2*pi*phase).
History and phase start at zero. After each output frame, phase advances by
shift_hz/sample_rate modulo one. All channels share that phase. Automation
changes its increment without resetting it. Zero shift holds the current phase;
it is an exact delayed identity only when that phase is zero. This is frequency
translation, not proportional pitch transposition or a transparent bypass.

`shift_hz` is finite, defaults to zero and accepts [-2000,2000] Hz, including
per-frame scoped modulation and ordinary parameter ramps. It applies at the
current output frame, after any upstream input alignment. The FIR approximation
weakens near DC and Nyquist; renderer qualification must report its usable band.
Negative frequencies reflect at DC and frequencies above Nyquist alias. There
is no protective filter or feedback.

Ordinary mix and warm bypass blend against the real branch delayed by 512 frames.
Their commands receive that intrinsic delay, matching the audio timeline. The
oscillator and FIR continue while bypassed. Input end supplies zero excitation
and drains 1,024 history frames; stop ends immediately. Snapshots include the
history, write index, phase, remaining tail and ordinary graph control state.
