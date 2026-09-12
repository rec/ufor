# Broadcast scores

A broadcast score is planned playout: named recorded, live, or relay sources and
sections with fixed, after-section, or cue starts. Cue starts may give an earliest
position and deadline. Each section has exactly one end rule: duration, fixed
position, or cue/source-end bounded by a maximum. Cue-dependent sections are
valid but reported as provisional by `provisional_sections`.

Sections declare cut, crossfade, or mix transitions; late-join behavior; and an
availability policy to replace, skip, or stop. Relay sources declare the buffer
they require before starting. An optional as-aired run records actual starts,
ends, cues, dropouts, replacements, source instances, local submission, remote
delivery, and delivery failures. Replaying that record never requires the original
live source. Ufor does not connect inputs or deliver output.
