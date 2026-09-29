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

7. **Medium, confirmed: permissive byte validity is called voice validity.**
   `DX7Voice.valid_data` (`ufor/dx7.py:51-62`) and
   `TX81ZVoice.valid_data` (`ufor/tx81z.py:12-23`) verify length and
   seven-bit bytes, while decoded operator fields have narrower domains.
   A structurally valid payload can yield an out-of-range `algorithm` or a
   later `ValidationError` from `.operator()` after the entry has been
   presented as valid. Either check semantic fields during validation or
   distinguish lossless/raw acceptance from decoded-voice validity in names,
   diagnostics, and tests.

9. **Medium, risk: exact unit conversion and recursive documents have no size
   bounds.** `ufor/expression.py:10-38` accepts unbounded numeric literals
   and exponentiation; very large powers can consume excessive CPU/memory
   before the finite-result check. Recursive provider JSON in
   `ufor/assets.py:95-126,210-226` and nested score declarations likewise
   have no depth/size limit. Establish a format or host input-budget policy and
   turn excessive or deeply nested input into an actionable validation error.

## Local I/O, concurrency, and exceptional conditions

14. **Medium, risk: library reads are unbounded and all-at-once.**
    `score_files` accumulates the complete tree, then `read_library` reads
    every file into memory, parses each document, and resolves the complete
    graph. A very large file, huge library, or user Python module that never
    returns can stall a host or exhaust memory. `KeyboardInterrupt` does
    propagate and per-file ordinary exceptions are diagnosed, as documented;
    they do not solve hangs or resource exhaustion. State whether the host
    must set file/count/time budgets or expose a bounded reader. Arbitrary
    Python code remains a trusted-code boundary, not a sandbox promise.

15. **Medium, risk: long acyclic reference chains can overflow recursion.**
    `Library._visit` in `ufor/library.py:144-183` recurses for each
    dependency, then `Composition` recursively instantiates parts. A valid
    deep graph can raise `RecursionError` rather than return a per-entry
    diagnostic. An iterative traversal or an explicit depth limit would
    preserve graceful handling of authored data.

## API and project structure

17. **Medium, confirmed: playback plans materialize all repetitions.**
    `SequenceSelection.repetitions` has no upper bound and `plan_playback`
    in `ufor/playback.py:75-145` builds a list of every iteration, rescanning
    all sequence events each time. A small authored sequence with a large
    repetition count can consume unbounded time and memory. A bounded
    request or lazy iterator should be considered if this API is used for
    long-running playback; keep the pure semantic operation independent of
    dispatch.

20. **Low, risk: source-format work is concentrated in one large module.**
    `ufor/sfz.py` is about 1,800 lines and contains parsing, metadata
    decoding, native compilation, diagnostics, and export. Changes to one
    direction require reviewing the other. A future focused change could
    separate import and export while sharing only actual common types and
    keeping the public `sfz` entry points stable. This is a maintenance risk,
    not a reason for a broad refactor now.

21. **Low, risk: small modules should be judged by domain role, not size.**
    `ufor/noise.py`, `ufor/references.py`, `ufor/preset.py`, and
    `ufor/number.py` are short, but several expose public concepts used by
    other modules. No safe consolidation is apparent merely from line counts.
    The conditional type-alias declaration in `ufor/number.py` is the one
    conspicuous readability issue; use a direct modern type alias when tooling
    allows it and check import users before moving anything.

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
