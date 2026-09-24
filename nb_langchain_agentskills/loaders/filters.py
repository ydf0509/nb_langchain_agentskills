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

    The ``allowed`` set is held by reference: mutating it in place changes
    visibility immediately (suits runtime toggles); wrap the loader again to
    switch modes statically.
    """

    def __init__(self, inner: SkillLoader, allowed: set[str] | None = None) -> None:
        self._inner = inner
        self._allowed = allowed

    @property
    def last_warnings(self):
        """Delegate to the inner loader so warnings stay current after re-scans."""
        return self._inner.last_warnings

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


class BlacklistSkillLoader(SkillLoader):
    """Hide a deny-list of skill names; everything else passes through.

    Mirror of :class:`AllowedSkillLoader`: a name in ``blocked`` is treated
    exactly like a missing skill in every method, so blocked skills cannot
    be listed, loaded, read or resolved either — filtering the list alone
    would leave them reachable.

    The ``blocked`` set is held by reference: mutating it in place changes
    visibility immediately (suits runtime toggles). ``blocked=None`` starts
    from an empty set, which hides nothing.
    """

    def __init__(self, inner: SkillLoader, blocked: set[str] | None = None) -> None:
        self._inner = inner
        self._blocked = blocked if blocked is not None else set()

    @property
    def last_warnings(self):
        """Delegate to the inner loader so warnings stay current after re-scans."""
        return self._inner.last_warnings

    def _check(self, name: str) -> None:
        if self._blocked and name in self._blocked:
            available = sorted(
                {m.name for m in self._inner.list_skills()} - self._blocked
            )
            raise SkillNotFoundError(name, available=available)

    def list_skills(self) -> list[SkillMetadata]:
        skills = self._inner.list_skills()
        if not self._blocked:
            return skills
        return [m for m in skills if m.name not in self._blocked]

    def load_skill(self, name: str) -> SkillContent:
        self._check(name)
        return self._inner.load_skill(name)

    def read_content(self, skill_name: str, file_path: str) -> str:
        self._check(skill_name)
        return self._inner.read_content(skill_name, file_path)

    def resolve_root(self, skill_name: str) -> Path:
        self._check(skill_name)
        return self._inner.resolve_root(skill_name)
