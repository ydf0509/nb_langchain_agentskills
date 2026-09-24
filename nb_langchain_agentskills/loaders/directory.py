"""Directory loader: recursive discovery with pruning, warnings and TTL caching."""

import fnmatch
import os
import threading
import time
from pathlib import Path

from ..exceptions import (
    SkillContentReadError,
    SkillLoadError,
    SkillNotFoundError,
)
from ..models import (
    MAX_FILE_CHARS,
    MAX_FILES_LISTED,
    TRUNCATION_NOTICE,
    SkillContent,
    SkillLoadWarning,
    SkillMetadata,
)
from ..parsing import metadata_from_frontmatter, parse_skill_md, read_text_file
from .base import SkillLoader

SKILL_MD = "SKILL.md"
DEFAULT_TTL_SECONDS = 60.0


class _Record:
    __slots__ = ("metadata", "root", "skill_md_path")

    def __init__(self, metadata: SkillMetadata, root: Path, skill_md_path: Path) -> None:
        self.metadata = metadata
        self.root = root
        self.skill_md_path = skill_md_path


class DirectorySkillLoader(SkillLoader):
    """Load skills from a local directory tree.

    Discovery is recursive with pruning: dot-directories and ``exclude_dirs``
    fnmatch patterns are never entered. Only exactly-named ``SKILL.md`` files
    are skills; case variants produce a warning. A duplicate name inside one
    source raises immediately. Invalid SKILL.md files are skipped and reported
    through ``last_warnings``.

    The skill list (name, description, root) is cached and refreshed
    automatically at most once every ``ttl_seconds`` (default 60): the first
    call after the TTL expires re-scans, so a long-running process picks up
    new and removed skills without anyone calling reload(). ``ttl_seconds=0``
    disables automatic refresh; :meth:`reload` always re-scans immediately.
    A failed scan keeps the previous list and still advances the TTL clock,
    so a broken directory fails at most once per TTL window.

    File contents are never cached: ``load_skill`` and ``read_content`` read
    from disk on every call, with the same character cap applied to both.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        exclude_dirs: list[str] | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.last_warnings = []
        self._root = Path(root).expanduser().resolve()
        if not self._root.is_dir():
            raise SkillLoadError(f"skills directory does not exist: {self._root}")
        self._exclude_dirs = list(exclude_dirs or [])
        self._ttl_seconds = float(ttl_seconds)
        self._lock = threading.Lock()
        self._last_scan = 0.0
        self._records: dict[str, _Record] = {}
        self.reload()

    def _is_excluded_dir(self, name: str) -> bool:
        return name.startswith(".") or any(
            fnmatch.fnmatch(name, pattern) for pattern in self._exclude_dirs
        )

    def reload(self) -> None:
        """Re-scan the directory tree immediately and rebuild the cached skill list."""
        with self._lock:
            self._scan()

    def _scan(self) -> None:
        warnings: list[SkillLoadWarning] = []
        records: dict[str, _Record] = {}
        try:
            for dirpath, dirnames, filenames in os.walk(self._root, followlinks=False):
                dirnames[:] = [d for d in dirnames if not self._is_excluded_dir(d)]
                variants = [f for f in filenames if f.lower() == SKILL_MD.lower()]
                if not variants:
                    continue
                found = SKILL_MD if SKILL_MD in variants else variants[0]
                path = Path(dirpath) / found
                if found != SKILL_MD:
                    warnings.append(
                        SkillLoadWarning(
                            str(path),
                            f"non-canonical file name '{found}': rename to 'SKILL.md' "
                            "so it is discovered on every platform",
                        )
                    )
                    continue
                try:
                    content = read_text_file(path)
                    frontmatter, _ = parse_skill_md(content)
                    metadata = metadata_from_frontmatter(frontmatter)
                except Exception as exc:
                    warnings.append(SkillLoadWarning(str(path), f"skipped: {exc}"))
                    continue
                root = path.parent
                if metadata.name in records:
                    raise SkillLoadError(
                        f"duplicate skill name '{metadata.name}' within one source: "
                        f"'{records[metadata.name].root}' and '{root}'"
                    )
                records[metadata.name] = _Record(metadata, root, path)
        finally:
            self.last_warnings = warnings
            self._last_scan = time.monotonic()
        self._records = records

    def _ensure_fresh(self) -> None:
        """Re-scan at most once per TTL window; a no-op until the TTL expires."""
        if self._ttl_seconds <= 0:
            return
        if time.monotonic() - self._last_scan < self._ttl_seconds:
            return
        with self._lock:
            if time.monotonic() - self._last_scan < self._ttl_seconds:
                return
            self._scan()

    def _get(self, name: str) -> _Record:
        self._ensure_fresh()
        record = self._records.get(name)
        if record is None:
            raise SkillNotFoundError(name, available=sorted(self._records))
        return record

    def list_skills(self) -> list[SkillMetadata]:
        self._ensure_fresh()
        return [self._records[name].metadata for name in sorted(self._records)]

    def load_skill(self, name: str) -> SkillContent:
        record = self._get(name)
        try:
            content = read_text_file(record.skill_md_path)
            _, body = parse_skill_md(content)
        except Exception as exc:
            raise SkillLoadError(
                f"failed to read SKILL.md for skill '{name}' at "
                f"'{record.skill_md_path}': {exc}"
            ) from exc
        if len(body) > MAX_FILE_CHARS:
            body = body[:MAX_FILE_CHARS] + TRUNCATION_NOTICE.format(limit=MAX_FILE_CHARS, total=len(body))
        return SkillContent(
            metadata=record.metadata,
            body=body,
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
                relative = rel / filename if str(rel) != "." else Path(filename)
                files.append(relative.as_posix())
        files.sort()
        if len(files) > MAX_FILES_LISTED:
            hidden = len(files) - MAX_FILES_LISTED
            return files[:MAX_FILES_LISTED] + [f"[+{hidden} more files not shown]"]
        return files
