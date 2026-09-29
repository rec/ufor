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

## Tests, documentation, and ownership

## Additional work beyond the prompt

None.
