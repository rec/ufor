"""Lazy resolution of the recursive score union for direct model imports."""

from collections.abc import Mapping

from .base import Model


class RecursiveModel(Model):
    @classmethod
    def model_rebuild(
        cls,
        *,
        force: bool = False,
        raise_errors: bool = True,
        _parent_namespace_depth: int = 2,
        _types_namespace: Mapping[str, object] | None = None,
    ) -> bool | None:
        from .score_types import ScoreValue

        namespace = {'ScoreValue': ScoreValue, **(_types_namespace or {})}
        return super().model_rebuild(
            force=force,
            raise_errors=raise_errors,
            _parent_namespace_depth=_parent_namespace_depth,
            _types_namespace=namespace,
        )
