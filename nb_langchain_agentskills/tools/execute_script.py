"""skill__execute_script: run a shell command inside a skill directory."""

from pathlib import Path
from typing import ClassVar

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from ..exceptions import SkillsError
from ..executor import CommandExecutor
from ..loaders.base import SkillLoader


class ExecuteScriptArgs(BaseModel):
    """Arguments for skill__execute_script."""

    model_config = ConfigDict(extra="forbid")

    skill_name: str = Field(description="Name of the skill this command belongs to.")
    command: str = Field(
        description=(
            "Full shell command to run, e.g. 'python scripts/fill.py --form a.pdf'. "
            "Executed with the platform shell (powershell on Windows, bash elsewhere) "
            "with the skill directory as the working directory."
        )
    )
    max_run_ms: int = Field(
        default=30_000,
        description="Timeout in milliseconds.",
    )
    working_directory: str | None = Field(
        default=None,
        description=(
            "Optional working directory. Relative paths resolve against the skill "
            "root; the resolved directory must stay inside the skill root."
        ),
    )


class ExecuteSkillTool(BaseTool):
    """Execute a shell command on behalf of a skill."""

    name: str = "skill__execute_script"
    description: str = (
        "Run a shell command belonging to a skill, e.g. one of the scripts "
        "the skill provides. Use skill__load_skill first to see the available "
        "scripts. Returns exit_code, duration_ms, stdout and stderr."
    )
    loader: SkillLoader
    args_schema: type[BaseModel] = ExecuteScriptArgs
    executor: CommandExecutor
    _not_serializable: ClassVar[bool] = True

    def _run(
        self,
        skill_name: str,
        command: str,
        max_run_ms: int = 30_000,
        working_directory: str | None = None,
    ) -> str:
        try:
            root = self.loader.resolve_root(skill_name)
        except SkillsError as exc:
            return f"Error: {exc}"

        if working_directory:
            candidate = Path(working_directory).expanduser()
            resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
            if not resolved.is_relative_to(root):
                return (
                    f"Error: working_directory '{working_directory}' resolves outside the "
                    f"skill root '{root}'. It must stay inside the skill directory."
                )
            if not resolved.is_dir():
                return f"Error: working_directory '{resolved}' does not exist."
        else:
            resolved = root

        pythonpath_dirs = [d for d in (root, root / "scripts") if d.is_dir()]
        try:
            result = self.executor.run(
                command,
                cwd=resolved,
                timeout_ms=max_run_ms,
                pythonpath_dirs=pythonpath_dirs,
            )
        except ValueError as exc:
            return f"Error: {exc}"
        except OSError as exc:
            return f"Error running command: {exc}"
        return result.to_text()
