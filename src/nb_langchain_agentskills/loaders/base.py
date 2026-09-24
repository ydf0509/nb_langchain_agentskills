"""Loader abstraction: the single seam for filtering, overlay and visibility."""

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import SkillContent, SkillMetadata


class SkillLoader(ABC):
    """Base class for all skill loaders.

    Subclass or wrap this to control which skills are visible and where they
    come from. Tools and the middleware never touch the filesystem directly;
    every path question goes through a loader.
    """

    last_warnings: list = []

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
