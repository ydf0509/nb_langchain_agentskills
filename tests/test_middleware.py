import pytest

from nb_langchain_agentskills.loaders import DirectorySkillLoader
from nb_langchain_agentskills.middleware import (
    ALL_TOOL_NAMES,
    SkillsMiddleware,
    _default_prompt_builder,
)
from conftest import write_skill


def test_zero_skills_degrades(tmp_path):
    middleware = SkillsMiddleware(DirectorySkillLoader(tmp_path))
    assert not middleware.has_visible_skills
    assert len(middleware.tools) == 4


def test_tools_registered_and_exclude(skill_tree):
    middleware = SkillsMiddleware(DirectorySkillLoader(skill_tree))
    assert middleware.has_visible_skills
    assert {tool.name for tool in middleware.tools} == set(ALL_TOOL_NAMES)
    excluded = SkillsMiddleware(
        DirectorySkillLoader(skill_tree), exclude_tools={"skill__list_skills"}
    )
    assert "skill__list_skills" not in {tool.name for tool in excluded.tools}
    assert len(excluded.tools) == 3


def test_exclude_unknown_name_raises(skill_tree):
    with pytest.raises(ValueError):
        SkillsMiddleware(DirectorySkillLoader(skill_tree), exclude_tools={"nope"})


def test_default_prompt_escapes_html(skill_tree):
    write_skill(skill_tree, "evil", "evil", "<b>&desc</b>")
    middleware = SkillsMiddleware(DirectorySkillLoader(skill_tree))
    assert "&lt;b&gt;&amp;desc&lt;/b&gt;" in middleware._skills_prompt


def test_custom_prompt_builder(skill_tree):
    middleware = SkillsMiddleware(
        DirectorySkillLoader(skill_tree),
        prompt_builder=lambda skills: "CUSTOM " + skills[0].name,
    )
    assert middleware._skills_prompt.startswith("CUSTOM ")
    assert middleware.has_visible_skills


def test_default_builder_empty():
    assert _default_prompt_builder([]) == ""


import time


class _FakeRequest:
    def __init__(self):
        self.system_message = None

    def override(self, **kwargs):
        clone = _FakeRequest()
        clone.system_message = kwargs.get("system_message")
        return clone


def test_prompt_refreshes_after_ttl(skill_tree):
    loader = DirectorySkillLoader(skill_tree, ttl_seconds=0.05)
    middleware = SkillsMiddleware(loader)
    write_skill(skill_tree, "late", "late", "Late skill")
    time.sleep(0.15)
    result = middleware.wrap_model_call(_FakeRequest(), lambda req: req)
    text = result.system_message.content[0]["text"]
    assert "late" in text
    assert "Late skill" in text
