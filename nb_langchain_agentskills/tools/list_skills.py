"""skill__list_skills: list all visible skills."""

import html
from typing import ClassVar

from langchain_core.tools import BaseTool

from ..exceptions import SkillsError
from ..loaders.base import SkillLoader


class ListSkillsTool(BaseTool):
    """List all available skills with their names and descriptions."""

    name: str = "skill__list_skills"
    description: str = (
        "List all available skills with their names and descriptions. "
        "The skills list is also included in the system prompt; call this "
        "only when you need to refresh or confirm what is available."
    )
    loader: SkillLoader
    _not_serializable: ClassVar[bool] = True

    def _run(self) -> str:
        try:
            skills = self.loader.list_skills()
        except SkillsError as exc:
            return f"Error: {exc}"
        if not skills:
            return "No skills available."
        return "\n".join(
            f"- **{html.escape(skill.name)}**: {html.escape(skill.description)}" for skill in skills
        )
