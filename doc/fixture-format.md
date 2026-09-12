# Fixture scores

Fixture scores carry semantic cues for logical fixtures. A profile defines numeric
parameters with units/ranges and discrete parameters with explicit choices. A
physical `FixturePatch` maps each logical fixture to universe and slot; changing
that map never changes cues. `universe_offset` explicitly derives an Art-Net wire
universe from a display universe. Ufor does not send DMX or Art-Net.
