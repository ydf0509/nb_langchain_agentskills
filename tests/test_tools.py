import os
import sys

import pytest
from pydantic import ValidationError

from nb_langchain_agentskills.executor import CommandExecutor
from nb_langchain_agentskills.loaders import DirectorySkillLoader
from nb_langchain_agentskills.tools import (
    ExecuteSkillTool,
    ListSkillsTool,
    LoadSkillTool,
    ReadContentTool,
)


@pytest.fixture
def loader(skill_tree):
    return DirectorySkillLoader(skill_tree)


def py_script(directory, code, name="probe.py"):
    path = directory / name
    path.write_text(code, encoding="utf-8")
    exe = sys.executable
    if os.name == "nt":
        return f'& "{exe}" "{path}"'
    return f'"{exe}" "{path}"'


def test_list_skills_tool(loader):
    out = ListSkillsTool(loader=loader)._run()
    assert "- **pdf**: Handle PDF files" in out
    assert "- **xlsx**: Handle Excel files" in out


def test_load_tool_format(loader, skill_tree):
    out = LoadSkillTool(loader=loader)._run("refs-demo")
    assert f"<skill_directory>\n{skill_tree / 'refs-demo'}\n</skill_directory>" in out
    body = (skill_tree / "refs-demo" / "SKILL.md").read_text(encoding="utf-8")
    assert f"<skill_instructions>\n{body.split('---', 2)[-1].strip()}\n</skill_instructions>" in out
    files_section = out.split("<skill_files>")[1].split("</skill_files>")[0]
    assert "- SKILL.md" in files_section
    assert "- references/notes.md" in files_section
    assert "- scripts/run.py" in files_section
    assert "- scripts/helper.py" in files_section


def test_load_tool_unknown_returns_error(loader):
    out = LoadSkillTool(loader=loader)._run("nope")
    assert out.startswith("Error")
    assert "pdf" in out


def test_read_tool(loader):
    tool = ReadContentTool(loader=loader)
    assert tool._run("refs-demo", "references/notes.md") == "notes content"
    assert "Error" in tool._run("refs-demo", "../outside")


def test_args_schema_forbid(loader):
    tool = LoadSkillTool(loader=loader)
    with pytest.raises(ValidationError):
        tool.args_schema.model_validate({"skill_name": "pdf", "bogus": 1})
    execute = ExecuteSkillTool(loader=loader, executor=CommandExecutor())
    with pytest.raises(ValidationError):
        execute.args_schema.model_validate({"skill_name": "pdf", "wrong": 1})


def test_execute_success(loader, skill_tree):
    tool = ExecuteSkillTool(loader=loader, executor=CommandExecutor())
    out = tool._run("refs-demo", py_script(skill_tree, "print(42)"))
    assert "exit_code: 0" in out
    assert "42" in out
    assert "duration_ms:" in out


def test_execute_pythonpath(loader, skill_tree):
    tool = ExecuteSkillTool(loader=loader, executor=CommandExecutor())
    code = 'import os; print(os.environ.get("PYTHONPATH", ""))'
    out = tool._run("refs-demo", py_script(skill_tree, code))
    assert str(skill_tree / "refs-demo") in out
    assert str(skill_tree / "refs-demo" / "scripts") in out


def test_execute_non_zero_returns_output(loader, skill_tree):
    tool = ExecuteSkillTool(loader=loader, executor=CommandExecutor())
    code = 'import sys; print("boom"); sys.exit(3)'
    out = tool._run("refs-demo", py_script(skill_tree, code))
    assert "exit_code: 3" in out
    assert "boom" in out


def test_execute_timeout_kills_tree(loader, skill_tree):
    tool = ExecuteSkillTool(loader=loader, executor=CommandExecutor())
    code = 'import time; print("started", flush=True); time.sleep(10)'
    out = tool._run("refs-demo", py_script(skill_tree, code), max_run_ms=1500)
    assert "timed_out: true" in out
    assert "started" in out


def test_execute_validations(loader):
    tool = ExecuteSkillTool(loader=loader, executor=CommandExecutor())
    assert tool._run("refs-demo", "echo hi", max_run_ms=0).startswith("Error")
    assert tool._run("refs-demo", "  ").startswith("Error")
    assert "outside the skill root" in tool._run(
        "refs-demo", "echo hi", working_directory="../outside"
    )
    assert tool._run("nope", "echo hi").startswith("Error")



from conftest import write_skill


def test_list_tool_escapes_html(tmp_path):
    write_skill(tmp_path, "evil", "evil", "<b>&desc</b>")
    loader = DirectorySkillLoader(tmp_path)
    out = ListSkillsTool(loader=loader)._run()
    assert "&lt;b&gt;&amp;desc&lt;/b&gt;" in out
    assert "<b>" not in out
