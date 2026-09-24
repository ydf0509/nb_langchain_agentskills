"""skill__load_skill: load full skill content with its real directory."""

from typing import ClassVar

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from ..exceptions import SkillsError
from ..loaders.base import SkillLoader


class LoadSkillArgs(BaseModel):
    """Arguments for skill__load_skill."""

    model_config = ConfigDict(extra="forbid")

    skill_name: str = Field(description="Name of the skill to load, from the available skills list.")


class LoadSkillTool(BaseTool):
    """Load a skill: root directory, full instructions and file list."""

    name: str = "skill__load_skill"
    description: str = (
        "Load a skill by name. Returns the skill's root directory on the first "
        "line, its full instructions, and the list of files inside the skill. "
        "Call this first whenever the user's request matches a skill in the "
        "available skills list, then follow the returned instructions."
    )
    loader: SkillLoader
    _not_serializable: ClassVar[bool] = True

    def _run(self, skill_name: str) -> str:
        try:
            content = self.loader.load_skill(skill_name)
        except SkillsError as exc:
            return f"Error loading skill '{skill_name}': {exc}"
        parts = [f"Skill directory: {content.root}", "", content.body]
        if content.files:
            parts.append("")
            parts.append("**Files** (use skill__read_content to read):")
            parts.extend(f"- {item}" for item in content.files)
        return "\n".join(parts)
