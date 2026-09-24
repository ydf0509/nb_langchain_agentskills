"""SKILL.md parser: YAML frontmatter + markdown body.

Reading is always done with ``utf-8-sig`` so BOM-prefixed files parse and
Windows locale encodings never leak in.
"""

from pathlib import Path
from typing import Any

import yaml

from .exceptions import SkillValidationError
from .models import SkillMetadata

_FRONTMATTER = "---"


def read_text_file(path: str | Path) -> str:
    """Read a text file as utf-8-sig (BOM tolerant)."""
    return Path(path).read_text(encoding="utf-8-sig")


def parse_skill_md(content: str) -> tuple[dict[str, Any], str]:
    """Split SKILL.md content into (frontmatter dict, markdown body).

    Only the first ``---`` pair is treated as frontmatter; any later ``---``
    in the body is preserved. Raises SkillValidationError with a precise
    reason when the file cannot be parsed.
    """
    stripped = content.lstrip("\ufeff").strip()
    if not stripped.startswith(_FRONTMATTER):
        raise SkillValidationError("SKILL.md must start with '---' frontmatter")

    rest = stripped[len(_FRONTMATTER):]
    end_idx = rest.find(f"\n{_FRONTMATTER}")
    if end_idx == -1:
        raise SkillValidationError("SKILL.md frontmatter is missing its closing '---'")

    after = rest[end_idx + len(_FRONTMATTER) + 1:]
    line_break = after.find("\n")
    closer = after if line_break == -1 else after[:line_break]
    if closer.strip():
        raise SkillValidationError(
            f"malformed frontmatter closing delimiter: '{closer.strip()}'"
        )
    body = "" if line_break == -1 else after[line_break + 1:].strip()

    try:
        frontmatter = yaml.safe_load(rest[:end_idx])
    except yaml.YAMLError as exc:
        raise SkillValidationError(f"invalid YAML in SKILL.md frontmatter: {exc}") from exc

    if not isinstance(frontmatter, dict):
        raise SkillValidationError("SKILL.md frontmatter must be a YAML mapping")
    return frontmatter, body


def metadata_from_frontmatter(frontmatter: dict[str, Any], source: str = "local") -> SkillMetadata:
    """Validate a frontmatter mapping and convert it to SkillMetadata.

    A ``source`` key in the frontmatter is reserved (provenance is set by the
    loader) and is discarded; do not use it in SKILL.md.
    """
    data = dict(frontmatter)
    data.pop("source", None)
    try:
        return SkillMetadata(source=source, **data)
    except Exception as exc:
        raise SkillValidationError(f"invalid skill metadata: {exc}") from exc
