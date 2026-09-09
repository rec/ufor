# Ufor: Universal Format

**A common language for things that happen in time.**

Recordings, sequences, mixes and instruments share portable, human-readable
definitions. Exact timing, explicit units and named connections keep their
meaning intact across applications.

Today, Ufor covers:

- Audio recordings and arrangements; MIDI, OSC, keystrokes and performance events.
- Tunings, scales and oscillator definitions, with fractional ratios and Scala import.
- Sample instruments, asset slices and SFZ conversion.
- Segment envelopes, LFOs and typed modulation routes.

The larger ambition includes lighting, LEDs, control voltages and other timed
data. Video is outside the scope.

The Python library provides frozen Pydantic models, validation, TOML interchange,
JSON Schema and reference calculations. Applications supply file access, devices
and audio rendering. Portable conformance cases lay the groundwork for other
language implementations.

Start with the [musical definitions](doc/musical-format.md),
[instruments](doc/instrument-format.md) or [modulation](doc/modulation-format.md).
The proposed [document composition design](doc/composition-design.md) describes
shared interfaces, nested mixes and sequence-driven instruments.
Explore the [schema](schema/documents.json) and [conformance cases](conformance/).

For development, use Python 3.13+:

```sh
uv sync
uv run pytest
```

Extracted from Recs and Tuney. MIT licensed.
