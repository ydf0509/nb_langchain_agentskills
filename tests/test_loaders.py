import pytest

from nb_langchain_agentskills.exceptions import (
    SkillContentReadError,
    SkillLoadError,
    SkillNotFoundError,
)
from nb_langchain_agentskills.loaders import DirectorySkillLoader
from conftest import write_skill


def test_nested_discovery_sorted(skill_tree):
    loader = DirectorySkillLoader(skill_tree)
    assert [m.name for m in loader.list_skills()] == ["pdf", "refs-demo", "xlsx"]


def test_empty_dir_ok(tmp_path):
    assert DirectorySkillLoader(tmp_path).list_skills() == []


def test_missing_dir_raises(tmp_path):
    with pytest.raises(SkillLoadError):
        DirectorySkillLoader(tmp_path / "nope")


def test_bad_skill_becomes_warning(tmp_path):
    d = tmp_path / "broken"
    d.mkdir()
    (d / "SKILL.md").write_text("---\ndescription: no name\n---\n", encoding="utf-8")
    loader = DirectorySkillLoader(tmp_path)
    assert loader.list_skills() == []
    assert loader.last_warnings
    assert "skipped" in loader.last_warnings[0].message


def test_duplicate_name_raises(tmp_path):
    write_skill(tmp_path, "a/dup", "dup")
    write_skill(tmp_path, "b/dup", "dup")
    with pytest.raises(SkillLoadError):
        DirectorySkillLoader(tmp_path)


def test_case_variant_warns(tmp_path):
    d = tmp_path / "lower"
    d.mkdir()
    (d / "skill.md").write_text("---\nname: lower\ndescription: d\n---\n", encoding="utf-8")
    loader = DirectorySkillLoader(tmp_path)
    assert loader.list_skills() == []
    assert loader.last_warnings


def test_hidden_and_excluded_dirs_pruned(tmp_path):
    write_skill(tmp_path, ".hidden/ghost", "ghost")
    write_skill(tmp_path, "archive-old/old", "old")
    loader = DirectorySkillLoader(tmp_path, exclude_dirs=["archive-*"])
    assert loader.list_skills() == []


def test_load_returns_root_body_files(skill_tree):
    loader = DirectorySkillLoader(skill_tree)
    content = loader.load_skill("refs-demo")
    assert content.root == skill_tree / "refs-demo"
    assert content.metadata.name == "refs-demo"
    assert "SKILL.md" in content.files
    assert "references/notes.md" in content.files
    assert "scripts/run.py" in content.files
    assert "scripts/helper.py" in content.files


def test_reload_picks_up_new_skill(tmp_path):
    loader = DirectorySkillLoader(tmp_path)
    assert loader.list_skills() == []
    write_skill(tmp_path, "later", "later")
    loader.reload()
    assert [m.name for m in loader.list_skills()] == ["later"]


def test_unknown_skill_lists_available(skill_tree):
    loader = DirectorySkillLoader(skill_tree)
    with pytest.raises(SkillNotFoundError) as info:
        loader.load_skill("nope")
    assert "pdf" in str(info.value)


def test_read_content_relative_and_absolute(skill_tree):
    loader = DirectorySkillLoader(skill_tree)
    assert loader.read_content("refs-demo", "references/notes.md") == "notes content"
    absolute = str(skill_tree / "refs-demo" / "references" / "notes.md")
    assert loader.read_content("refs-demo", absolute) == "notes content"


def test_read_content_traversal_rejected(skill_tree):
    loader = DirectorySkillLoader(skill_tree)
    with pytest.raises(SkillContentReadError):
        loader.read_content("refs-demo", "../../outside.txt")
    with pytest.raises(SkillContentReadError):
        loader.read_content("refs-demo", str(skill_tree / "pdf" / "SKILL.md"))


def test_read_content_missing_file(skill_tree):
    loader = DirectorySkillLoader(skill_tree)
    with pytest.raises(SkillContentReadError):
        loader.read_content("refs-demo", "references/missing.md")


def test_read_content_binary_rejected(tmp_path):
    d = tmp_path / "bin"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: bin\ndescription: d\n---\n", encoding="utf-8")
    (d / "blob.bin").write_bytes(b"\xff\xfe\x00\x00\xff")
    loader = DirectorySkillLoader(tmp_path)
    with pytest.raises(SkillContentReadError):
        loader.read_content("bin", "blob.bin")


def test_read_content_truncation(tmp_path):
    d = tmp_path / "big"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: big\ndescription: d\n---\n", encoding="utf-8")
    (d / "big.txt").write_text("x" * 200_050, encoding="utf-8")
    loader = DirectorySkillLoader(tmp_path)
    text = loader.read_content("big", "big.txt")
    assert "[truncated" in text


def test_load_skill_body_is_realtime(skill_tree):
    loader = DirectorySkillLoader(skill_tree)
    assert "Body." in loader.load_skill("pdf").body
    path = skill_tree / "pdf" / "SKILL.md"
    path.write_text("---\nname: pdf\ndescription: Handle PDF files\n---\n\nUPDATED BODY\n", encoding="utf-8")
    assert "UPDATED BODY" in loader.load_skill("pdf").body


def test_list_requires_reload_for_new_skill(skill_tree):
    loader = DirectorySkillLoader(skill_tree)
    before = len(loader.list_skills())
    write_skill(skill_tree, "brandnew", "brandnew")
    assert len(loader.list_skills()) == before
    loader.reload()
    assert len(loader.list_skills()) == before + 1


import time


def test_ttl_auto_refresh_list(tmp_path):
    loader = DirectorySkillLoader(tmp_path, ttl_seconds=0.05)
    assert loader.list_skills() == []
    write_skill(tmp_path, "later", "later")
    time.sleep(0.15)
    assert [m.name for m in loader.list_skills()] == ["later"]


def test_ttl_zero_disables_auto_refresh(tmp_path):
    loader = DirectorySkillLoader(tmp_path, ttl_seconds=0)
    write_skill(tmp_path, "later", "later")
    time.sleep(0.15)
    assert loader.list_skills() == []
    loader.reload()
    assert [m.name for m in loader.list_skills()] == ["later"]


def test_ttl_on_miss_load(tmp_path):
    loader = DirectorySkillLoader(tmp_path, ttl_seconds=0.05)
    write_skill(tmp_path, "fresh", "fresh")
    time.sleep(0.15)
    assert loader.load_skill("fresh").metadata.name == "fresh"
    assert loader.resolve_root("fresh") == tmp_path / "fresh"



import threading
import time

from nb_langchain_agentskills.loaders.base import SkillLoader
from nb_langchain_agentskills.models import SkillLoadWarning


def test_load_skill_body_truncated(tmp_path):
    d = tmp_path / "big"
    d.mkdir()
    body = "x" * 200_050
    (d / "SKILL.md").write_text(f"---\nname: big\ndescription: d\n---\n\n{body}\n", encoding="utf-8")
    loader = DirectorySkillLoader(tmp_path)
    content = loader.load_skill("big")
    assert "[truncated" in content.body
    assert len(content.body) < 200_100


def test_list_files_cap(tmp_path):
    d = tmp_path / "many"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: many\ndescription: d\n---\n", encoding="utf-8")
    for i in range(250):
        (d / f"f{i:03}.txt").write_text("x", encoding="utf-8")
    loader = DirectorySkillLoader(tmp_path)
    files = loader.load_skill("many").files
    assert len(files) == 201
    assert files[0] == "SKILL.md"
    assert files[-1].startswith("[+51 more files not shown]")


def test_last_warnings_not_shared_between_subclass_instances():
    class _Minimal(SkillLoader):
        def list_skills(self):
            return []

        def load_skill(self, name):
            raise SkillNotFoundError(name)

        def read_content(self, skill_name, file_path):
            raise SkillNotFoundError(skill_name)

        def resolve_root(self, skill_name):
            raise SkillNotFoundError(skill_name)

    a = _Minimal()
    b = _Minimal()
    a.last_warnings.append(SkillLoadWarning("x", "y"))
    assert b.last_warnings == []
    assert a.last_warnings == [SkillLoadWarning("x", "y")]


def test_scan_failure_advances_ttl_clock(tmp_path):
    write_skill(tmp_path, "a/dup", "dup")
    loader = DirectorySkillLoader(tmp_path, ttl_seconds=0.05)
    time.sleep(0.15)
    write_skill(tmp_path, "b/dup", "dup")
    with pytest.raises(SkillLoadError):
        loader.list_skills()
    assert [m.name for m in loader.list_skills()] == ["dup"]


def test_concurrent_ttl_single_rescan(tmp_path, monkeypatch):
    loader = DirectorySkillLoader(tmp_path, ttl_seconds=0.05)
    write_skill(tmp_path, "a", "a")
    time.sleep(0.15)
    counter = {"n": 0}
    original = loader._scan

    def counting_scan():
        counter["n"] += 1
        original()

    monkeypatch.setattr(loader, "_scan", counting_scan)
    results: list = []
    errors: list = []

    def worker():
        try:
            results.append(sorted(m.name for m in loader.list_skills()))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert results and all(r == ["a"] for r in results)
    assert counter["n"] == 1


def test_exact_skill_md_preferred_over_variant(tmp_path):
    write_skill(tmp_path, "mixed", "mixed")
    (tmp_path / "mixed" / "skill.md").write_text("---\nname: mixed\ndescription: d\n---\n", encoding="utf-8")
    loader = DirectorySkillLoader(tmp_path)
    assert [m.name for m in loader.list_skills()] == ["mixed"]
    assert loader.last_warnings == []
