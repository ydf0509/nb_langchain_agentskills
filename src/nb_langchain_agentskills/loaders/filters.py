"""Visibility filter wrapper around any loader."""

from pathlib import Path

from ..exceptions import SkillNotFoundError
from ..models import SkillContent, SkillMetadata
from .base import SkillLoader


class AllowedSkillLoader(SkillLoader):
    """Expose only an explicit allow-list of skill names.

    ``allowed=None`` exposes everything. A name outside the allow-list is
    treated exactly like a missing skill in every method, so filtered skills
    cannot be loaded or executed either — filtering the list alone would be a
    security hole.
    """

    def __init__(self, inner: SkillLoader, allowed: set[str] | None = None) -> None:
        self.last_warnings = inner.last_warnings
        self._inner = inner
        self._allowed = allowed

    def _check(self, name: str) -> None:
        if self._allowed is not None and name not in self._allowed:
            available = (
                sorted(self._allowed & {m.name for m in self._inner.list_skills()})
                if self._allowed
                else []
            )
            raise SkillNotFoundError(name, available=available)

    def list_skills(self) -> list[SkillMetadata]:
        skills = self._inner.list_skills()
        if self._allowed is None:
            return skills
        return [metadata for metadata in skills if metadata.name in self._allowed]

    def load_skill(self, name: str) -> SkillContent:
        self._check(name)
        return self._inner.load_skill(name)

    def read_content(self, skill_name: str, file_path: str) -> str:
        self._check(skill_name)
        return self._inner.read_content(skill_name, file_path)

    def resolve_root(self, skill_name: str) -> Path:
        self._check(skill_name)
        return self._inner.resolve_root(skill_name)
