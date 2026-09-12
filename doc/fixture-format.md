# Fixture scores

Fixture scores carry semantic cues for logical fixtures. A profile defines numeric
parameters with units/ranges and discrete parameters with explicit choices. Its
channel encodings declare one or two DMX slots, byte order, numeric range or
discrete byte table. The profile also declares whether disconnect/stop blacks out,
fades, or holds its last state.

A physical `FixturePatch` maps each logical fixture to universe and slot; changing
that map never changes cues. `universe_offset` explicitly derives an Art-Net wire
universe from a display universe. Multiple writers for a fixture parameter at one
tick require an authored compositor rule.

`RawDmxCapture` preserves exact universe frames, slot count, optional sequence,
patch contract, synchronization method, and measured multi-universe skew. Raw
playback bypasses semantic remapping and therefore requires that contract. A
`PixelPatch` separately maps stable layout light names to a device and LED index;
layouts also name their coordinate frame. Ufor does not send DMX or Art-Net.
