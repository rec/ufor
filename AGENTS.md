# Ufor

Ufor is the shared format library, not an application or rendering engine.
Keep definitions and mathematical semantics independent of consumers and host
libraries. Import symbols directly from their defining modules; do not add
re-exports or initialization side effects to __init__.py.

Use Python 3.13, uv, frozen Pydantic models where possible, standard-library
types, and explicit type hints. Preserve exact fractions and native integer
timelines. Keep specification and language-neutral conformance examples in
agreement. Audio generation and sampler implementation are deferred.

For Python/data changes run pytest, Ruff, formatting, ty check ufor,
pyupgrade --py313-plus on changed Python, and git diff --check. Commit and push
requested changes; make dependency changes separate commits. Preserve unrelated
work and never switch existing branches or create merge commits.
