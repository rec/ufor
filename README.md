# Ufor: Universal Format

**A common language for things that happen in time.**

Recordings, sequences, mixes and instruments share portable, human-readable
definitions. Exact timing, explicit units and named connections keep their
meaning intact across applications.

A **score** is a saveable description of material, a process, or a composition.
Scores can contain named **parts**, each using another score. Their interfaces
expose named inputs, outputs and parameters. See the [composition design](doc/composition-design.md).

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
The implemented [score composition design](doc/composition-design.md) describes
shared interfaces, nested mixes and sequence-driven instruments.
Explore the [schema](schema/scores.json) and [conformance cases](conformance/).

The [VL70m SysEx proof of concept](doc/vl70m-sysex-example.md) implements lossless
dump inspection and explicit patch relocation with a partial MIDI description.
Device communication and integration into scores remain deferred.

For development, use Python 3.13+:

```sh
uv sync
uv run pytest
```

Extracted from Recs and Tuney. MIT licensed.
