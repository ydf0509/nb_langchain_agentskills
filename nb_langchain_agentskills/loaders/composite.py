"""Composite loader: merges sources, later ones override earlier ones."""

import logging
import threading
import time
from pathlib import Path

from ..exceptions import SkillNotFoundError
from ..models import SkillContent, SkillLoadWarning, SkillMetadata
from .base import SkillLoader

logger = logging.getLogger("nb_langchain_agentskills")

DEFAULT_TTL_SECONDS = 60.0


class CompositeSkillLoader(SkillLoader):
    """Merge multiple loaders into one namespace, **last wins**.

    Sources are ordered generic -> specific, e.g. ``[builtin, user, project]``:
    a later source overrides earlier ones on name conflicts. This matches
    deepagents and is the opposite of langchain-agentskills (first wins).

    The merged view is a single dict keyed by skill name; the winner's record
    (including its root path) wins everywhere, so ``list / load / read /
    resolve_root`` can never disagree. The visible list is sorted by name,
    independent of source order.

    The merged list is cached and refreshed automatically at most once every
    ``ttl_seconds`` (default 60); each source loader refreshes itself on its
    own TTL when asked. ``ttl_seconds=0`` disables automatic refresh;
    :meth:`reload` always re-merges immediately. A failed re-merge keeps the
    previous view and still advances the TTL clock.
    """

    def __init__(self, loaders: list[SkillLoader], *, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        if not loaders:
            raise ValueError("CompositeSkillLoader requires at least one loader")
        self.last_warnings = []
        self._loaders = list(loaders)
        self._ttl_seconds = float(ttl_seconds)
        self._lock = threading.Lock()
        self._last_merge = 0.0
        self.reload()

    def reload(self) -> None:
        """Re-merge from all sources immediately and refresh warnings."""
        with self._lock:
            self._merge()

    def _merge(self) -> None:
        warnings: list[SkillLoadWarning] = []
        merged: dict[str, tuple[int, SkillMetadata]] = {}
        try:
            for index, loader in enumerate(self._loaders):
                warnings.extend(
                    SkillLoadWarning(warning.path, f"[source {index}] {warning.message}")
                    for warning in loader.last_warnings
                )
                for metadata in loader.list_skills():
                    previous = merged.get(metadata.name)
                    if previous is not None:
                        message = (
                            f"skill '{metadata.name}' from source {index} overrides "
                            f"the one from source {previous[0]}"
                        )
                        logger.debug(message)
                        warnings.append(SkillLoadWarning(metadata.name, message))
                    merged[metadata.name] = (index, metadata)
        finally:
            self.last_warnings = warnings
            self._last_merge = time.monotonic()
        self._merged = merged

    def _ensure_fresh(self) -> None:
        """Re-merge at most once per TTL window; a no-op until the TTL expires."""
        if self._ttl_seconds <= 0:
            return
        if time.monotonic() - self._last_merge < self._ttl_seconds:
            return
        with self._lock:
            if time.monotonic() - self._last_merge < self._ttl_seconds:
                return
            self._merge()

    def _get_loader(self, name: str) -> SkillLoader:
        self._ensure_fresh()
        entry = self._merged.get(name)
        if entry is None:
            raise SkillNotFoundError(name, available=sorted(self._merged))
        return self._loaders[entry[0]]

    def list_skills(self) -> list[SkillMetadata]:
        self._ensure_fresh()
        return [metadata for _, metadata in sorted(self._merged.values(), key=lambda item: item[1].name)]

    def load_skill(self, name: str) -> SkillContent:
        return self._get_loader(name).load_skill(name)

    def read_content(self, skill_name: str, file_path: str) -> str:
        return self._get_loader(skill_name).read_content(skill_name, file_path)

    def resolve_root(self, skill_name: str) -> Path:
        return self._get_loader(skill_name).resolve_root(skill_name)
