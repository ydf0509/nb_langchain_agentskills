"""Exception hierarchy for nb_langchain_agentskills."""


class SkillsError(Exception):
    """Base exception for all nb_langchain_agentskills errors."""


class SkillNotFoundError(SkillsError):
    """Raised when a requested skill is not visible or does not exist."""

    def __init__(self, skill_name: str, available: list[str] | None = None) -> None:
        self.skill_name = skill_name
        self.available = list(available or [])
        message = f"Skill not found: {skill_name}"
        if self.available:
            message += f". Available skills: {', '.join(self.available)}"
        super().__init__(message)


class SkillValidationError(SkillsError):
    """Raised when a SKILL.md file is missing or has invalid metadata."""


class SkillLoadError(SkillsError):
    """Raised when a skill source cannot be scanned or loaded."""


class SkillContentReadError(SkillsError):
    """Raised when a file cannot be read from within a skill root.

    The message always states what was passed, where the skill root is,
    and how a valid path should look, so the caller can self-correct.
    """

    def __init__(self, skill_name: str, file_path: str, skill_root: str, hint: str = "") -> None:
        self.skill_name = skill_name
        self.file_path = file_path
        self.skill_root = skill_root
        message = (
            f"Cannot read '{file_path}' from skill '{skill_name}'. "
            f"The skill root is '{skill_root}'. Pass a path relative to the "
            f"skill root (e.g. 'references/notes.md') or an absolute path "
            f"inside the root."
        )
        if hint:
            message += f" {hint}"
        super().__init__(message)
