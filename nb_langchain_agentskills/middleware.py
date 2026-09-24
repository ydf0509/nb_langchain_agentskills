"""Middleware: inject the skills list into the system prompt and register tools."""

import html
import logging
from typing import Callable

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import SystemMessage

from .exceptions import SkillsError
from .executor import CommandExecutor
from .loaders.base import SkillLoader
from .models import SkillMetadata
from .tools import ExecuteSkillTool, ListSkillsTool, LoadSkillTool, ReadContentTool

ALL_TOOL_NAMES = frozenset(
    {
        "skill__list_skills",
        "skill__load_skill",
        "skill__read_content",
        "skill__execute_script",
    }
)

PromptBuilder = Callable[[list[SkillMetadata]], str]

logger = logging.getLogger("nb_langchain_agentskills")


def _default_prompt_builder(skills: list[SkillMetadata]) -> str:
    if not skills:
        return ""
    lines = [
        "<available_skills>",
        "The skills below match specific kinds of tasks. When the user's request "
        "matches a skill's description, call skill__load_skill with that skill's "
        "name first and follow its instructions exactly.",
        "",
    ]
    for skill in skills:
        lines.append(f"- **{html.escape(skill.name)}**: {html.escape(skill.description)}")
    lines.append("</available_skills>")
    return "\n".join(lines)


class SkillsMiddleware(AgentMiddleware):
    """Register the four skill tools and inject the skills list.

    The injected prompt follows the loader's view: before every model call the
    visible skills are compared against the previously rendered signature, and
    the prompt is rebuilt only when the list actually changed (e.g. a skill was
    added after the loader's TTL re-scan). A scan failure keeps the last good
    prompt instead of breaking the model call.
    """

    def __init__(
        self,
        loader: SkillLoader,
        *,
        executor: CommandExecutor | None = None,
        exclude_tools: set[str] | None = None,
        prompt_builder: PromptBuilder | None = None,
        enable_pythonpath: bool = True,
    ) -> None:
        super().__init__()
        exclude = set(exclude_tools or [])
        unknown = exclude - ALL_TOOL_NAMES
        if unknown:
            raise ValueError(f"unknown tool names in exclude_tools: {sorted(unknown)}")

        self._loader = loader
        self._builder = prompt_builder or _default_prompt_builder
        self._signature: tuple | None = None
        self._skills_prompt = ""
        self._refresh_prompt()

        run_executor = executor or CommandExecutor(enable_pythonpath=enable_pythonpath)
        factories = {
            "skill__list_skills": lambda: ListSkillsTool(loader=loader),
            "skill__load_skill": lambda: LoadSkillTool(loader=loader),
            "skill__read_content": lambda: ReadContentTool(loader=loader),
            "skill__execute_script": lambda: ExecuteSkillTool(loader=loader, executor=run_executor),
        }
        self.tools = [factory() for name, factory in factories.items() if name not in exclude]

    def _refresh_prompt(self) -> None:
        try:
            skills = self._loader.list_skills()
        except SkillsError as exc:
            logger.debug("skills refresh failed, keeping last prompt: %s", exc)
            return
        signature = tuple((skill.name, skill.description) for skill in skills)
        if signature != self._signature:
            self._signature = signature
            self._skills_prompt = self._builder(skills)

    @property
    def has_visible_skills(self) -> bool:
        """True when at least one skill was rendered into the prompt."""
        self._refresh_prompt()
        return bool(self._skills_prompt.strip())

    def _system_with_skills(self, existing: SystemMessage | None) -> SystemMessage | None:
        if not self._skills_prompt:
            return existing
        addendum = "\n\n" + self._skills_prompt
        if existing is None:
            return SystemMessage(content=[{"type": "text", "text": addendum}])
        blocks = list(existing.content_blocks) + [{"type": "text", "text": addendum}]
        return SystemMessage(content=blocks)

    def wrap_model_call(self, request, handler):
        self._refresh_prompt()
        return handler(request.override(system_message=self._system_with_skills(request.system_message)))

    async def awrap_model_call(self, request, handler):
        self._refresh_prompt()
        return await handler(request.override(system_message=self._system_with_skills(request.system_message)))
