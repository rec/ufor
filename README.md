# Ufor: Universal Format

**A common language for things that happen in time.**

Recordings, sequences, mixes and instruments share portable, human-readable
definitions. Exact timing, explicit units and named connections keep their
meaning intact across applications.

A **score** is a saveable description of material, a process, or a composition.
Scores can contain named **parts**, each using another score. Their interfaces
expose named inputs, outputs and parameters. See the [composition design](doc/composition-design.md).

Today, Ufor covers:

- User score libraries, literal selectors, Python declarations and reusable presets.
- Audio recordings and arrangements; MIDI, OSC, keystrokes and performance events.
- Tunings, scales and oscillator definitions, with fractional ratios and Scala import.
- Sample instruments, asset slices and SFZ conversion.
- Segment envelopes, LFOs and typed modulation routes.
- Scalar timeline automation for gain, frequency and logical gates, with explicit units.
- Light animation descriptions, arbitrary component counts, layouts and wiring,
  with exact composition and shared parameter controls.

The larger ambition includes fixture control, control voltages and other timed
data. Video is outside the scope.

The Python library provides frozen Pydantic models, validation, TOML interchange,
JSON Schema and reference calculations. An explicit library reader loads configured local files; applications supply devices
and audio rendering. Portable conformance cases lay the groundwork for other
language implementations.

Start with the [musical definitions](doc/musical-format.md),
[instruments](doc/instrument-format.md), [modulation](doc/modulation-format.md)
or [light animations](doc/light-format.md). The [Lyte port instructions](doc/port-lyte.md)
describe the remaining host work; Lyte has not yet been migrated.
The implemented [score composition design](doc/composition-design.md) describes
shared interfaces, nested mixes and sequence-driven instruments.
See [user libraries](doc/library.md) for configuration, selection and host integration.
Explore the [schema](schema/scores.json) and [conformance cases](conformance/).
See [scalar automation](doc/automation-format.md) for editable curves and examples.

The [VL70m SysEx proof of concept](doc/vl70m-sysex-example.md) implements lossless
dump inspection and explicit patch relocation with a partial MIDI description.
Device communication and integration into scores remain deferred.

For development, use Python 3.13+:

```sh
uv sync
uv run pytest
```

Extracted from Recs, Tuney and Lyte. MIT licensed.

Sequence cropping, seeking, loop ownership, and UMP storage are described in
[sequence playback](doc/sequence-playback.md).
