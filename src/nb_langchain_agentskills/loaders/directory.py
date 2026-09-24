"""Directory loader: recursive discovery with pruning, warnings and caching."""

import fnmatch
import os
from pathlib import Path

from ..exceptions import (
    SkillContentReadError,
    SkillLoadError,
    SkillNotFoundError,
)
from ..models import (
    MAX_FILE_CHARS,
    TRUNCATION_NOTICE,
    SkillContent,
    SkillLoadWarning,
    SkillMetadata,
)
from ..parsing import metadata_from_frontmatter, parse_skill_md, read_text_file
from .base import SkillLoader

SKILL_MD = "SKILL.md"


class _Record:
    __slots__ = ("metadata", "root", "skill_md_path", "body")

    def __init__(self, metadata: SkillMetadata, root: Path, skill_md_path: Path, body: str) -> None:
        self.metadata = metadata
        self.root = root
        self.skill_md_path = skill_md_path
        self.body = body


class DirectorySkillLoader(SkillLoader):
    """Load skills from a local directory tree.

    Discovery is recursive with pruning: dot-directories and ``exclude_dirs``
    fnmatch patterns are never entered. Only exactly-named ``SKILL.md`` files
    are skills; case variants produce a warning. A duplicate name inside one
    source raises immediately. Invalid SKILL.md files are skipped and reported
    through ``last_warnings``.

    Results are cached at scan time; call :meth:`reload` after editing skills
    on disk.
    """

    def __init__(self, root: str | Path, *, exclude_dirs: list[str] | None = None) -> None:
        self.last_warnings: list[SkillLoadWarning] = []
        self._root = Path(root).expanduser().resolve()
        if not self._root.is_dir():
            raise SkillLoadError(f"skills directory does not exist: {self._root}")
        self._exclude_dirs = list(exclude_dirs or [])
        self._records: dict[str, _Record] = {}
        self.reload()

    def _is_excluded_dir(self, name: str) -> bool:
        return name.startswith(".") or any(
            fnmatch.fnmatch(name, pattern) for pattern in self._exclude_dirs
        )

    def reload(self) -> None:
        """Re-scan the directory tree and rebuild the cache."""
        self.last_warnings = []
        records: dict[str, _Record] = {}
        for dirpath, dirnames, filenames in os.walk(self._root, followlinks=False):
            dirnames[:] = [d for d in dirnames if not self._is_excluded_dir(d)]
            matches = [f for f in filenames if f.lower() == SKILL_MD.lower()]
            if not matches:
                continue
            found = matches[0]
            path = Path(dirpath) / found
            if found != SKILL_MD:
                self.last_warnings.append(
                    SkillLoadWarning(
                        str(path),
                        f"non-canonical file name '{found}': rename to 'SKILL.md' "
                        "so it is discovered on every platform",
                    )
                )
                continue
            try:
                content = read_text_file(path)
                frontmatter, body = parse_skill_md(content)
                metadata = metadata_from_frontmatter(frontmatter)
            except Exception as exc:
                self.last_warnings.append(SkillLoadWarning(str(path), f"skipped: {exc}"))
                continue
            root = path.parent
            if metadata.name in records:
                raise SkillLoadError(
                    f"duplicate skill name '{metadata.name}' within one source: "
                    f"'{records[metadata.name].root}' and '{root}'"
                )
            records[metadata.name] = _Record(metadata, root, path, body)
        self._records = records

    def _get(self, name: str) -> _Record:
        record = self._records.get(name)
        if record is None:
            raise SkillNotFoundError(name, available=sorted(self._records))
        return record

    def list_skills(self) -> list[SkillMetadata]:
        return [self._records[name].metadata for name in sorted(self._records)]

    def load_skill(self, name: str) -> SkillContent:
        record = self._get(name)
        return SkillContent(
            metadata=record.metadata,
            body=record.body,
            files=self._list_files(record.root),
            root=record.root,
        )

    def read_content(self, skill_name: str, file_path: str) -> str:
        root = self.resolve_root(skill_name)
        candidate = Path(file_path).expanduser()
        resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        if not resolved.is_relative_to(root):
            raise SkillContentReadError(skill_name, file_path, str(root))
        if not resolved.is_file():
            raise SkillContentReadError(skill_name, file_path, str(root), hint="The file does not exist.")
        try:
            text = resolved.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            raise SkillContentReadError(
                skill_name, file_path, str(root), hint="The file appears to be binary and cannot be read as text."
            ) from None
        except OSError as exc:
            raise SkillContentReadError(skill_name, file_path, str(root), hint=f"OS error: {exc}") from exc
        if len(text) > MAX_FILE_CHARS:
            text = text[:MAX_FILE_CHARS] + TRUNCATION_NOTICE.format(limit=MAX_FILE_CHARS, total=len(text))
        return text

    def resolve_root(self, skill_name: str) -> Path:
        return self._get(skill_name).root

    def _list_files(self, root: Path) -> list[str]:
        files: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if not self._is_excluded_dir(d)]
            rel = Path(dirpath).relative_to(root)
            for filename in sorted(filenames):
                if filename.startswith("."):
                    continue
                if filename == SKILL_MD and str(rel) == ".":
                    continue
                relative = rel / filename if str(rel) != "." else Path(filename)
                files.append(relative.as_posix())
        return sorted(files)
