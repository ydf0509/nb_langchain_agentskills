from pathlib import Path

import pytest


def write_skill(base, rel, name, description="A test skill", body="Body.", extra=""):
    d = base / rel
    d.mkdir(parents=True, exist_ok=True)
    text = f"---\nname: {name}\ndescription: {description}\n{extra}---\n\n{body}\n"
    path = d / "SKILL.md"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def skill_tree(tmp_path):
    write_skill(tmp_path, "pdf", "pdf", "Handle PDF files")
    write_skill(tmp_path, "nested/deep/xlsx", "xlsx", "Handle Excel files")
    write_skill(tmp_path, "refs-demo", "refs-demo", "Demo references")
    refs = tmp_path / "refs-demo" / "references"
    refs.mkdir()
    (refs / "notes.md").write_text("notes content", encoding="utf-8")
    scripts = tmp_path / "refs-demo" / "scripts"
    scripts.mkdir()
    (scripts / "run.py").write_text("print('hi')", encoding="utf-8")
    (scripts / "helper.py").write_text("x = 1", encoding="utf-8")
    return tmp_path
