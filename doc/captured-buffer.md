# Captured-buffer foundation

`CapturedBuffer` is the shared definition for triggered `reverse`, `scrub` and
`stutter` modes. These definitions and actions are the first slice; renderer
integration and the transition/command-timing profile remain unfinished.

The prepared `window_seconds` defaults to 0.25 seconds and must be positive and
at most two seconds. Capture selects the most recent complete input window
before its action frame. Insufficient history is an explicit error. Recording
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

Input end stops recording and prevents new captures. An active reverse finishes
once; held stutter/scrub playback continues until release or stop. Such a held
graph is intentionally not drained merely because its input ended.

Playback fades, stutter seam timing, stationary scrub output and delayed-command
capacity are still being selected. This foundation does not qualify any renderer
or define those remaining details. The implementation must document them before
the complete profile is considered usable.

`conformance/captured-buffer.json` supplies the three definitions and the
capture/release action shapes. The foundation tests cover interchange, named
layout preservation, zero declared latency, lifecycle classification and the
duration/position restrictions.
