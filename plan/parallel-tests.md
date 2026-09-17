# Parallel unit tests

## Goal

Run uFor's complete unit-test suite concurrently while preserving its format and
mathematical guarantees. The normal developer command should reduce wall-clock
time, while `-n 0` remains the single-process debugging escape hatch.

## Current safety assessment

uFor's test suite is suitable for process parallelism:

- It tests pure Pydantic models, codec operations, exact arithmetic, and
  language-neutral conformance data. It does not start an audio engine, open a
  device, or perform network I/O.
- Tests that write libraries, Python score files, or copied conformance trees
  use pytest's per-test `tmp_path`.
- The library test that changes `HOME` sets it to its own `tmp_path` with
  `monkeypatch`, so it cannot alter the user's real configuration or another
  worker's state.
- Checked-in conformance and documentation inputs are read-only. VL70 tests
  construct and inspect byte sequences in memory.

## Implementation

1. Add unpinned `pytest-xdist` to the development dependency group and refresh
   `uv.lock` in a separate dependency commit.
2. Add pytest configuration so the normal command is:

   ```console
   uv run pytest -n auto --dist=worksteal
   ```

   `-n auto` uses the machine's physical CPU count. `worksteal` balances the
   uneven model, codec, conformance, and library modules without imposing an
   unnecessary file-level ordering.
3. Update the development command in `README.md` to match. Do not make test
   behavior depend on a particular CPU count: developers may use `-n N` to
   cap workers or `-n 0` for a deterministic interactive debugging session.
4. Keep output capture enabled. pytest-xdist cannot provide ordinary live
   `-s` output; run a focused test with `-n 0 -s` when that is needed.
5. Run the complete suite serially and in parallel at least three times. Record
   wall-clock time and confirm the same collection and pass counts.
6. If a failure exposes shared state, repair the owning test or fixture so its
   filesystem state remains under `tmp_path`. Use `pytest.mark.xdist_group`
   only for a genuinely shared resource, not to preserve incidental ordering.

## Acceptance

- `uv run pytest -n auto --dist=worksteal` repeatedly passes with the same test
  count as `uv run pytest -n 0`.
- Parallel tests do not read or write the real home directory, modify checked-in
  conformance data, open devices, or use network I/O.
- The parallel command has a materially lower wall-clock time than a serial run
  measured on the same machine.
- Focused single-process debugging remains available through `-n 0`.

## References

pytest-xdist documents automatic worker selection, `-n 0`, and the
`worksteal` distribution mode at
<https://pytest-xdist.readthedocs.io/en/stable/distribution.html>.

## Additional work beyond the prompt

None.
