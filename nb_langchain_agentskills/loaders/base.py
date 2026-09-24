"""Loader abstraction: the single seam for filtering, overlay and visibility."""

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import SkillContent, SkillMetadata, SkillLoadWarning


class SkillLoader(ABC):
    """Base class for all skill loaders.

    Subclass or wrap this to control which skills are visible and where they
    come from. Tools and the middleware never touch the filesystem directly;
    every path question goes through a loader.

    ``last_warnings`` is per-instance (never shared across instances) and
    defaults to an empty list; implementations that scan should overwrite it
    with the warnings of the most recent scan.
    """

    @property
    def last_warnings(self) -> list[SkillLoadWarning]:
        warnings = self.__dict__.get("_last_warnings")
        if warnings is None:
            warnings = []
            self.__dict__["_last_warnings"] = warnings
        return warnings

    @last_warnings.setter
    def last_warnings(self, value: list) -> None:
        self.__dict__["_last_warnings"] = list(value)

    @abstractmethod
    def list_skills(self) -> list[SkillMetadata]:
        """Return metadata for all visible skills."""

    @abstractmethod
    def load_skill(self, name: str) -> SkillContent:
        """Return full content (body, file list, root) for one skill."""

    @abstractmethod
    def read_content(self, skill_name: str, file_path: str) -> str:
        """Read any file that lives inside the named skill root."""

    @abstractmethod
    def resolve_root(self, skill_name: str) -> Path:
        """Return the absolute path of the skill root directory."""
