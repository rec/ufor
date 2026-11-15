# Captured-buffer profile

`CapturedBuffer` is the shared definition for triggered `reverse`, `scrub` and
`stutter` modes. The shared contract below specifies bounded storage and exact
traversal; renderer qualification is supplied by enge.

The prepared `window_seconds` defaults to 0.25 seconds and must be positive and
at most two seconds. Capture selects the most recent complete input window
before its aligned execution frame. Duration rounds to frames using nearest
ties-to-even. At least 129 frames are required for the fixed 64-frame fades.
Insufficient history is an explicit error. Recording
continues during captured playback, so another capture selects a fresh window.
Storage must be prepared before rendering; capture may copy the bounded window
but must not allocate callback storage.

Reverse traverses the captured region backward once. Stutter repeats it until
release. Scrub exposes a normalized `position` in [0,1], default zero, using
linear interpolation and synchronized traversal across named channels. Nonzero
authored positions and position automation require scrub mode. Position uses the
ordinary ratio modulation unit. Mix defaults to fully wet; ordinary mix and
warm-bypass controls use the existing effect contract. The processor declares
zero intrinsic latency; it replays previously recorded audio rather than
delaying all live input by its window length.

`CaptureAction` targets a captured-buffer processor. `CaptureReleaseAction`
releases its held playback and is a lifecycle action for batch admission.
Both use the existing exact frame and ordinal ordering. They are invalid on
other processor kinds. Stop remains immediate and graph-wide.

Input end stops recording and prevents new captures, including on its first
ended frame. An active reverse finishes
once; held stutter/scrub playback continues until release or stop. Such a held
graph is intentionally not drained merely because its input ended.

Playback starts from dry. Capture fades linearly from the current dry/captured
mixture to a fresh region over 64 frames; release retimes each current captured
gain toward zero over 64 frames. Recording and traversal continue under ordinary
mix or warm bypass. Two prepared captured regions support a recapture crossfade;
capture rejects while both are occupied. Release on idle playback is harmless.

Reverse reads newest to oldest, one frame per output frame. Its final 64 frames
apply an additional linear tail envelope reaching zero on the oldest frame,
blending back to dry. A release or recapture cannot extend this natural ending.
Stutter uses a 64-frame overlap seam and a period of window_frames-64. For cycle
offset p below 64, blend the tail sample at period+p with the head sample at p,
using head weight p/64; otherwise read p directly. Capture starts at cycle offset
zero, the beginning of that tail/head seam. All channels share traversal.

Scrub maps position 0 to the oldest sample and 1 to the newest sample. It uses
linear interpolation, without an autonomous clock. A stationary position holds
the sample value, including DC; abrupt position changes may click. Authors use
explicit parameter ramps or modulation for motion and Highpass for DC removal.

Capture/release commands follow upstream latency to the processor's aligned
input timeline, preserving frame/ordinal order. `maximum_pending_actions`
defaults to 64 and must be a positive integer. Its preallocated queue rejects
exhaustion explicitly. Captures execute before that frame's input is written,
and require input to be live at execution time. Pending commands, recording
history, both regions, traversal and fades are snapshot state. Capture copies
the fixed window into prepared storage; that work scales with window and channel
count even though it allocates no callback storage.

`conformance/captured-buffer.json` supplies the three definitions and the
capture/release action shapes. The foundation tests cover interchange, named
layout preservation, zero declared latency, lifecycle classification and the
duration/position restrictions.
