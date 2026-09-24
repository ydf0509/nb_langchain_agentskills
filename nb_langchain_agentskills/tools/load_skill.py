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
        "Load a skill by name. Returns an XML document with three sections: "
        "skill_directory (the skill's root directory), skill_files (the files "
        "inside the skill, including SKILL.md itself), and skill_instructions "
        "(the skill's full instructions). "
        "Call this first whenever the user's request matches a skill in the "
        "available skills list, then follow the returned instructions."
    )
    loader: SkillLoader
    args_schema: type[BaseModel] = LoadSkillArgs
    _not_serializable: ClassVar[bool] = True

    def _run(self, skill_name: str) -> str:
        try:
            content = self.loader.load_skill(skill_name)
        except SkillsError as exc:
            return f"Error loading skill '{skill_name}': {exc}"
        files = "\n".join(f"- {item}" for item in content.files)
        return (
            f"<skill_directory>\n{content.root}\n</skill_directory>\n"
            f"\n"
            f"<skill_files>\n{files}\n</skill_files>\n"
            f"\n"
            f"<skill_instructions>\n{content.body}\n</skill_instructions>"
        )
