# Slideshow scores

A slideshow score is an editable image or video performance. It has named sealed
assets, ordered items, normalized crop/rotation/fit values, required `alt` text,
and optional longer descriptions. Each item has a positive native-tick duration
and automatic, manual, or named-cue advance. A video also has a finite source
range; its embedded audio is not accompaniment.

`DirectorySelection` is an import recipe. Hosts enumerate candidate relative
paths, then `resolve_selection` applies the declared recursion, include/exclude
patterns, and Unicode code-point path ordering without filesystem access. Hosts
turn the result into named sealed assets and ordinary slides. Later directory
changes cannot alter that result.

Transitions join adjacent items only and cannot exceed either visible duration.
An accompaniment independently selects a sealed audio asset, slideshow start, and
finite source range. Its manual policy is explicit: continue, pause, or seek.
Audible accompaniment requires caption tracks. A caption track contains ordered,
non-overlapping timed captions in one language or names a sealed caption asset;
its offset makes synchronization inspectable.

A run record stores ordered entered, advanced, backed-up, held, cue, transition,
caption, and failure observations, so an as-presented replay does not need to
guess what an operator did. Image/video decoding, display output, audio playback,
caption rendering, and cue delivery are host work.

An omitted slide `advance` inherits `default_advance`; explicit `automatic`
overrides even a manual or cue default. Hosts resolve each slide with
`slide.advance or slideshow.default_advance`. The effective mode requires a cue
name exactly when it is `cue`. Serialization preserves omission separately from
an explicit mode. Each adjacent slide pair may have only one transition, cuts
have zero duration, and every embedded caption must use its track's language.
