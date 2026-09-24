"""Composite loader: merges sources, later ones override earlier ones."""

import logging
from pathlib import Path

from ..exceptions import SkillNotFoundError
from ..models import SkillContent, SkillLoadWarning, SkillMetadata
from .base import SkillLoader

logger = logging.getLogger("nb_langchain_agentskills")


class CompositeSkillLoader(SkillLoader):
    """Merge multiple loaders into one namespace, **last wins**.

    Sources are ordered generic -> specific, e.g. ``[builtin, user, project]``:
    a later source overrides earlier ones on name conflicts. This matches
    deepagents and is the opposite of langchain-agentskills (first wins).

    The merged view is a single dict keyed by skill name; the winner's record
    (including its root path) wins everywhere, so ``list / load / read /
    resolve_root`` can never disagree.
    """

    def __init__(self, loaders: list[SkillLoader]) -> None:
        self.last_warnings: list[SkillLoadWarning] = []
        if not loaders:
            raise ValueError("CompositeSkillLoader requires at least one loader")
        self._loaders = list(loaders)
        self.reload()

    def reload(self) -> None:
        """Re-merge from all sources and refresh warnings."""
        self.last_warnings = []
        merged: dict[str, tuple[int, SkillMetadata]] = {}
        for index, loader in enumerate(self._loaders):
            self.last_warnings.extend(
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
                    self.last_warnings.append(SkillLoadWarning(metadata.name, message))
                merged[metadata.name] = (index, metadata)
        self._merged = merged

    def _get_loader(self, name: str) -> SkillLoader:
        entry = self._merged.get(name)
        if entry is None:
            raise SkillNotFoundError(name, available=sorted(self._merged))
        return self._loaders[entry[0]]

    def list_skills(self) -> list[SkillMetadata]:
        return [metadata for _, metadata in self._merged.values()]

    def load_skill(self, name: str) -> SkillContent:
        return self._get_loader(name).load_skill(name)

    def read_content(self, skill_name: str, file_path: str) -> str:
        return self._get_loader(skill_name).read_content(skill_name, file_path)

    def resolve_root(self, skill_name: str) -> Path:
        return self._get_loader(skill_name).resolve_root(skill_name)
