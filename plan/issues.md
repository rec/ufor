# uFor code and documentation audit

This is a review of the current source, tests, examples, conformance files, schema,
and format documentation. **Confirmed** means the cited code permits the stated
behavior; **risk** means the failure needs a particular host workload or concurrent
use. Priorities indicate impact, not an implementation order. These are open
questions and defects, not promises to add host facilities to the format library.

The boundary matters: uFor does not acquire network assets, run audio devices, or
manage playback services. There is no uFor service shutdown sequence, network
retry loop, or lock that could deadlock. Network intermittency, stream stopping,
and cache recovery are host responsibilities. The local library loader and
configuration writer are uFor's significant I/O paths.

## Format and semantic correctness

5. **Medium, confirmed: Scale silently drops misspelled fields.**
   `Scale.model_config = ConfigDict(extra='ignore')` in `ufor/scale.py:56`
   overrides the project's default `extra='forbid'`. For example, a typo in
   `note_names` is accepted and the default alphabet is used. `ScaleScore`
   exposes this through TOML. Unless the editing workflow deliberately relies
   on extra fields, reject them and test an authored typo.

6. **Medium, confirmed: “frozen” scores have mutable nested collections.**
   `ufor/base.py:10-13` freezes model attributes, but fields such as
   `AudioDescription.channels` (`ufor/assets.py:169-178`),
   `RecordingScore.assets`, and `EventSequence.events` are lists. Callers can
   mutate them after validation and bypass uniqueness, reference, order, or
   content checks. Some entry points revalidate via `model_dump()`, but pure
   readers can observe invalid state. Document the mutation boundary and
   choose a consistent validation or immutable-snapshot strategy where the
   public API relies on frozen models.

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

12. **Medium, risk: concurrent Python-score loads share a temporary module
    slot.** `python_score` in `ufor/library_files.py:182-218` installs a
    deterministic key in global `sys.modules` and restores the prior value in
    `finally`. Two threads reading the same library can interleave installs
    and removals; imports during execution can see the other thread's module.
    Serialize that critical section or give concurrent executions distinct
    identities while preserving stable definition identity. Add a concurrent
    read test if threaded use is supported.

13. **Medium, risk: the symlink-skip check does not protect the subsequent
    open.** `score_files` checks `file.is_symlink()` in
    `ufor/library_files.py:159-179`, then `read_library` later calls
    `file.read_bytes()` at line 69. Another process can replace the path with
    a symlink between those operations, so a library advertised as skipping
    links can read outside its root. Clarify whether library roots are trusted
    mutable directories; if confinement is promised, open using an approach
    that enforces it on the opened file.

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

16. **Low, risk: walk-time filesystem errors can still escape the diagnostic
    boundary.** `root.walk(on_error=...)` reports traversal errors, but
    `file.is_symlink()` in `score_files` is outside the per-file `try` block.
    Permission changes or disappearing entries can raise `OSError` and abort
    the whole read. Capture and report those as file diagnostics.

## API and project structure

17. **Medium, confirmed: playback plans materialize all repetitions.**
    `SequenceSelection.repetitions` has no upper bound and `plan_playback`
    in `ufor/playback.py:75-145` builds a list of every iteration, rescanning
    all sequence events each time. A small authored sequence with a large
    repetition count can consume unbounded time and memory. A bounded
    request or lazy iterator should be considered if this API is used for
    long-running playback; keep the pure semantic operation independent of
    dispatch.

18. **Medium, confirmed: audio-gap validation scales poorly.**
    `AudioStream.timeline` in `ufor/recording.py:57-109` scans all fragments
    and all unmapped fragments for every gap, in addition to sorting them.
    Large recovered recording journals can therefore spend quadratic time
    validating otherwise valid gaps. Use sorted interval passes and add a
    many-fragment regression case.

19. **Medium, risk: public asset names blur acquisition and identity.**
    `DownloadLocation` and `GitFileLocation` in `ufor/assets.py` are source
    declarations with pinned byte identity, while `StreamLocation` and
    `PythonProviderLocation` have no `content`. Yet all are called `Asset`,
    and `finite_audio_required()` sounds like an enforcement helper although
    it only returns a Boolean. This invites a consumer to assume an asset
    is ready to play or cache. The location plan documents the distinction;
    make the API docs and helper name equally explicit about declaration,
    finite output, and host acquisition.

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

23. **Medium, confirmed: the cache plan's implementation status is stale.**
    `plan/asset-cache.md` still says the host cache is only proposed, but
    reccy now has `reccy/runtime/assets.py` for finite object storage and
    `reccy/runtime/capture.py` for captures. The plan can misdirect future
    work into duplicating that service inside uFor. Update the status to
    distinguish the implemented generic store/capture core from source
    acquisition adapters and any remaining policy gaps. Do not import reccy
    into the portable format library.

24. **Medium, risk: hostile and failure-path tests are thinner than happy-path
    conformance.** Existing tests cover malformed scores, symlinks,
    individual Python module failures, interrupt propagation, and schema
    drift. There is no focused coverage for concurrent library reads/writes,
    failed config replacement, long acyclic dependency chains, oversized
    expression/JSON inputs, or non-finite assets in sealed recording and
    slideshow definitions. Add focused cases alongside fixes; avoid broad
    tests that reassert every field already covered by Pydantic and the
    conformance corpus.

25. **Low, confirmed: recording verification language spans two owners.**
    `doc/recording-format.md` describes `recs record check`, finalization,
    payload verification, and recovery, while uFor's `RecordingScore` only
    validates the declaration and references. Mark host verification claims
    explicitly as reccy behavior and keep uFor's guarantee limited to
    structural/semantic validation. This also clarifies what network or
    storage failures can be handled here versus by a host.

## Additional work beyond the prompt

None.
