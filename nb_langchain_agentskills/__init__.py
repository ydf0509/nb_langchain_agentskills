"""nb_langchain_agentskills: Agent Skills management for LangChain."""

from .exceptions import (
    SkillContentReadError,
    SkillLoadError,
    SkillNotFoundError,
    SkillValidationError,
    SkillsError,
)
from .executor import CommandExecutor, ExecutionResult
from .loaders import (
    AllowedSkillLoader,
    BlacklistSkillLoader,
    CompositeSkillLoader,
    DirectorySkillLoader,
    SkillLoader,
)
from .middleware import ALL_TOOL_NAMES, SkillsMiddleware
from .models import SkillContent, SkillLoadWarning, SkillMetadata
from .shell_resolve import (
    ShellInfo,
    build_shell_command,
    decode_output,
    render_shell_fact,
    render_shell_guidance,
    render_shell_report,
    reset_shell_cache,
    resolve_shell,
)

__version__ = "0.9.1"

__all__ = [
    "ALL_TOOL_NAMES",
    "AllowedSkillLoader",
    "BlacklistSkillLoader",
    "CommandExecutor",
    "CompositeSkillLoader",
    "DirectorySkillLoader",
    "ExecutionResult",
    "ShellInfo",
    "SkillContent",
    "SkillLoadError",
    "SkillLoader",
    "SkillLoadWarning",
    "SkillMetadata",
    "SkillNotFoundError",
    "SkillValidationError",
    "SkillsError",
    "SkillsMiddleware",
    "__version__",
    "build_shell_command",
    "decode_output",
    "render_shell_fact",
    "render_shell_guidance",
    "render_shell_report",
    "reset_shell_cache",
    "resolve_shell",
]
