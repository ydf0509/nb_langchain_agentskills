"""skill__read_content: read any file inside a skill root."""

from typing import ClassVar

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from ..exceptions import SkillsError
from ..loaders.base import SkillLoader


class ReadContentArgs(BaseModel):
    """Arguments for skill__read_content."""

    model_config = ConfigDict(extra="forbid")

    skill_name: str = Field(description="Name of the skill the file belongs to.")
    file_path: str = Field(
        description=(
            "Path relative to the skill root (e.g. 'references/notes.md', "
            "'scripts/fill.py'). Absolute paths inside the skill root are also accepted."
        )
    )


class ReadContentTool(BaseTool):
    """Read any file that lives inside a skill."""

    name: str = "skill__read_content"
    description: str = (
        "Read a file from a skill: reference documents, scripts, templates, "
        "any file inside the skill directory. Use skill__load_skill first to "
        "see the file list. Paths outside the skill root are rejected."
    )
    loader: SkillLoader
    _not_serializable: ClassVar[bool] = True

    def _run(self, skill_name: str, file_path: str) -> str:
        try:
            return self.loader.read_content(skill_name, file_path)
        except SkillsError as exc:
            return f"Error reading '{file_path}' from skill '{skill_name}': {exc}"
