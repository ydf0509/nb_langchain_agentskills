import pytest

from nb_langchain_agentskills.exceptions import SkillNotFoundError
from nb_langchain_agentskills.loaders import (
    AllowedSkillLoader,
    CompositeSkillLoader,
    DirectorySkillLoader,
)
from conftest import write_skill


def test_last_wins_everywhere(tmp_path):
    write_skill(tmp_path, "global/pdf", "pdf", "global desc", body="global body")
    write_skill(tmp_path, "project/pdf", "pdf", "project desc", body="project body")
    (tmp_path / "project" / "pdf" / "marker.txt").write_text("winner", encoding="utf-8")
    composite = CompositeSkillLoader(
        [
            DirectorySkillLoader(tmp_path / "global"),
            DirectorySkillLoader(tmp_path / "project"),
        ]
    )
    assert composite.list_skills()[0].description == "project desc"
    assert composite.resolve_root("pdf") == tmp_path / "project" / "pdf"
    assert "project body" in composite.load_skill("pdf").body
    assert composite.read_content("pdf", "marker.txt") == "winner"
    assert any("overrides" in w.message for w in composite.last_warnings)


def test_composite_unknown_skill(tmp_path):
    write_skill(tmp_path, "s/pdf", "pdf")
    composite = CompositeSkillLoader([DirectorySkillLoader(tmp_path / "s")])
    with pytest.raises(SkillNotFoundError):
        composite.load_skill("nope")


def test_allowed_filter(tmp_path):
    write_skill(tmp_path, "pdf", "pdf")
    write_skill(tmp_path, "xlsx", "xlsx")
    inner = DirectorySkillLoader(tmp_path)
    filtered = AllowedSkillLoader(inner, allowed={"pdf"})
    assert [m.name for m in filtered.list_skills()] == ["pdf"]
    filtered.load_skill("pdf")
    with pytest.raises(SkillNotFoundError):
        filtered.load_skill("xlsx")
    with pytest.raises(SkillNotFoundError):
        filtered.resolve_root("xlsx")
    assert len(AllowedSkillLoader(inner).list_skills()) == 2


import time


def test_composite_ttl_auto_refresh(tmp_path):
    write_skill(tmp_path, "project/pdf", "pdf")
    project = DirectorySkillLoader(tmp_path / "project", ttl_seconds=0.05)
    composite = CompositeSkillLoader([project], ttl_seconds=0.05)
    assert [m.name for m in composite.list_skills()] == ["pdf"]
    write_skill(tmp_path, "project/xlsx", "xlsx")
    time.sleep(0.15)
    assert {m.name for m in composite.list_skills()} == {"pdf", "xlsx"}
    assert composite.resolve_root("xlsx") == tmp_path / "project" / "xlsx"



def test_composite_list_sorted_by_name(tmp_path):
    write_skill(tmp_path, "project/pdf", "pdf")
    write_skill(tmp_path, "global/abc", "abc")
    composite = CompositeSkillLoader(
        [
            DirectorySkillLoader(tmp_path / "project"),
            DirectorySkillLoader(tmp_path / "global"),
        ]
    )
    assert [m.name for m in composite.list_skills()] == ["abc", "pdf"]


from nb_langchain_agentskills import BlacklistSkillLoader


def test_blacklist_filter(tmp_path):
    write_skill(tmp_path, "pdf", "pdf")
    write_skill(tmp_path, "xlsx", "xlsx")
    inner = DirectorySkillLoader(tmp_path)
    filtered = BlacklistSkillLoader(inner, blocked={"pdf"})
    assert [m.name for m in filtered.list_skills()] == ["xlsx"]
    filtered.load_skill("xlsx")
    with pytest.raises(SkillNotFoundError):
        filtered.load_skill("pdf")
    with pytest.raises(SkillNotFoundError):
        filtered.read_content("pdf", "SKILL.md")
    with pytest.raises(SkillNotFoundError):
        filtered.resolve_root("pdf")
    assert len(BlacklistSkillLoader(inner).list_skills()) == 2


def test_blacklist_held_by_reference(tmp_path):
    write_skill(tmp_path, "pdf", "pdf")
    write_skill(tmp_path, "xlsx", "xlsx")
    blocked: set = set()
    filtered = BlacklistSkillLoader(DirectorySkillLoader(tmp_path), blocked=blocked)
    assert len(filtered.list_skills()) == 2
    blocked.add("pdf")
    assert [m.name for m in filtered.list_skills()] == ["xlsx"]
    blocked.discard("pdf")
    assert len(filtered.list_skills()) == 2


def test_blacklist_error_lists_available(tmp_path):
    write_skill(tmp_path, "pdf", "pdf")
    write_skill(tmp_path, "xlsx", "xlsx")
    filtered = BlacklistSkillLoader(DirectorySkillLoader(tmp_path), blocked={"pdf"})
    with pytest.raises(SkillNotFoundError) as info:
        filtered.load_skill("pdf")
    assert "xlsx" in str(info.value)
