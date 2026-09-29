# uFor code and documentation audit

This is a review of the current source, tests, examples, conformance files, schema,
and format documentation. **Confirmed** means the cited code permits the stated
behavior; **risk** means the failure needs a particular host workload or concurrent
use. Priorities indicate impact, not an implementation order. These are open
questions and defects, not promises to add host facilities to the format library.

The boundary matters: uFor does not acquire network assets, run audio devices, or
manage playback services. There is no uFor service shutdown sequence or network
retry loop. The library configuration writer uses one advisory file lock;
Python-score execution does not hold it. Network intermittency, stream stopping,
and cache recovery are host responsibilities. The local library loader and
configuration writer are uFor's significant I/O paths.

## Format and semantic correctness

## Local I/O, concurrency, and exceptional conditions

## API and project structure

20. **Low, risk: source-format work is concentrated in one large module.**
    `ufor/sfz.py` is about 1,800 lines and contains parsing, metadata
    decoding, native compilation, diagnostics, and export. Changes to one
    direction require reviewing the other. A future focused change could
    separate import and export while sharing only actual common types and
    keeping the public `sfz` entry points stable. This is a maintenance risk,
    not a reason for a broad refactor now.

22. **Low, confirmed: checked-in schema and type unions require manual
    synchronization.** `ufor/codec.py:21-88` repeats the score union exposed
    by `ufor/score_types.py`; `schema/scores.json` is a roughly 12,000-line
    generated artifact. The test in `test/test_instrument_document.py:94`
    detects schema drift, which is good, but a new score kind still needs
    synchronized edits in several locations. Consider deriving the public
    signatures from one declared union when a score kind is next added;
    avoid changing the generated schema by hand.

## Tests, documentation, and ownership

25. **Low, confirmed: recording verification language spans two owners.**
    `doc/recording-format.md` describes `recs record check`, finalization,
    payload verification, and recovery, while uFor's `RecordingScore` only
    validates the declaration and references. Mark host verification claims
    explicitly as reccy behavior and keep uFor's guarantee limited to
    structural/semantic validation. This also clarifies what network or
    storage failures can be handled here versus by a host.

## Additional work beyond the prompt

None.
