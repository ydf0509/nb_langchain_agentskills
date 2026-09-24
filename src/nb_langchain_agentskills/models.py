"""Pydantic models for skill metadata, content and scan warnings."""

import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_FILE_CHARS = 200_000
TRUNCATION_NOTICE = "\n\n[truncated: showing first {limit} of {total} characters]"


@dataclass
class SkillLoadWarning:
    """A non-fatal problem found while scanning a skill source."""

    path: str
    message: str


class SkillMetadata(BaseModel):
    """Lightweight skill metadata parsed from SKILL.md frontmatter.

    Unknown frontmatter fields are preserved via ``extra="allow"`` and
    round-trip through ``model_dump``.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    description: str
    license: str | None = None
    compatibility: dict | None = None
    metadata: dict | None = None
    allowed_tools: list[str] | None = None
    source: str = "local"

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        if "--" in value:
            raise ValueError("consecutive hyphens are not allowed in skill name")
        if len(value) > MAX_NAME_LENGTH or not SKILL_NAME_PATTERN.match(value):
            raise ValueError(
                "skill name must be 1-64 lowercase alphanumeric characters "
                "with single interior hyphens, no leading/trailing hyphen"
            )
        return value

    @field_validator("description")
    @classmethod
    def _check_description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("skill description cannot be empty")
        if len(value) > MAX_DESCRIPTION_LENGTH:
            raise ValueError(
                f"skill description must be at most {MAX_DESCRIPTION_LENGTH} characters"
            )
        return value


class SkillContent(BaseModel):
    """Full skill content returned by ``load_skill``."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    metadata: SkillMetadata
    body: str
    files: list[str] = []
    root: Path
