# Slideshow scores

A slideshow score is an editable still-image performance. It has named sealed
assets, ordered slides, normalized crop/rotation/fit values, required `alt` text,
and optional longer descriptions. Each slide has a positive native-tick duration
and automatic, manual, or named-cue advance.

`DirectorySelection` is an import recipe. Hosts enumerate candidate relative
paths, then `resolve_selection` applies the declared recursion, include/exclude
patterns, and Unicode code-point path ordering without filesystem access. Hosts
turn the result into named sealed assets and ordinary slides. Later directory
changes cannot alter that result.

Transitions join adjacent slides only. A run record stores ordered entered,
advanced, backed-up, held, and cue decisions, so an as-presented replay does not
need to guess what an operator did. This first profile has no image decoding,
screen output, video, audio accompaniment, caption tracks, or device cue delivery.
