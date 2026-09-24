"""Shell command executor for skill scripts.

Runs a full command string through the platform shell, enforces a timeout
that kills the entire process tree, captures stdout/stderr with truncation,
and can prepend skill directories to PYTHONPATH.

On Windows the command runs via ``powershell -EncodedCommand`` (base64 of the
UTF-16LE script), so quoting inside the command survives the command line
verbatim. Output is decoded as UTF-8 first and falls back to the ANSI code
page (``mbcs``, e.g. GBK on Chinese Windows) and then the preferred locale
encoding when the bytes are not valid UTF-8, so native tools that print in
the console codepage remain readable even under Python's UTF-8 mode.
"""

import base64
import locale
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_MS = 30_000
MAX_OUTPUT_CHARS = 60_000

_POWERSHELL_EXIT_TAIL = (
    '; if ($LASTEXITCODE -is [int]) { exit $LASTEXITCODE } else { exit 0 }'
)


@dataclass
class ExecutionResult:
    """Structured result of one command execution."""

    command: str
    exit_code: int | None
    duration_ms: int
    stdout: str
    stderr: str
    timed_out: bool

    def to_text(self) -> str:
        parts = [
            f"exit_code: {self.exit_code}",
            f"duration_ms: {self.duration_ms}",
        ]
        if self.timed_out:
            parts.append("timed_out: true")
        parts.append("")
        parts.append("stdout:")
        parts.append(self.stdout or "(empty)")
        parts.append("")
        parts.append("stderr:")
        parts.append(self.stderr or "(empty)")
        return "\n".join(parts)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[truncated: showing first {limit} of {len(text)} characters]"


def _fallback_encodings() -> list[str]:
    encodings: list[str] = []
    if os.name == "nt":
        encodings.append("mbcs")
    preferred = locale.getpreferredencoding(False)
    if preferred and preferred.lower() != "utf-8":
        encodings.append(preferred)
    return encodings


def _decode_output(data: bytes) -> str:
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        for encoding in _fallback_encodings():
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return data.decode("utf-8", errors="replace")


def _build_shell_command(command: str) -> list[str]:
    if os.name == "nt":
        script = command + _POWERSHELL_EXIT_TAIL
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        return ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
    return ["bash", "-c", command]


def _apply_pythonpath(env: dict[str, str], dirs: list[Path]) -> None:
    prepend = os.pathsep.join(str(d) for d in dirs)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{prepend}{os.pathsep}{existing}" if existing else prepend


class CommandExecutor:
    """Execute skill commands with timeout, process-tree kill and truncation."""

    def __init__(self, *, enable_pythonpath: bool = True) -> None:
        self.enable_pythonpath = enable_pythonpath

    def run(
        self,
        command: str,
        *,
        cwd: Path,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        pythonpath_dirs: list[Path] | None = None,
    ) -> ExecutionResult:
        if not command or not command.strip():
            raise ValueError("command must be a non-empty string")
        if timeout_ms <= 0:
            raise ValueError("max_run_ms must be a positive number of milliseconds")

        env = os.environ.copy()
        if self.enable_pythonpath and pythonpath_dirs:
            _apply_pythonpath(env, pythonpath_dirs)

        popen_kwargs: dict = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "cwd": str(cwd),
            "env": env,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        start = time.monotonic()
        proc = subprocess.Popen(_build_shell_command(command), **popen_kwargs)

        stdout_buf: list[bytes] = []
        stderr_buf: list[bytes] = []
        read_out = threading.Thread(target=lambda: stdout_buf.append(proc.stdout.read() or b""))
        read_err = threading.Thread(target=lambda: stderr_buf.append(proc.stderr.read() or b""))
        read_out.start()
        read_err.start()

        timed_out = False
        try:
            proc.wait(timeout=timeout_ms / 1000)
            t_end = time.monotonic()
        except subprocess.TimeoutExpired:
            timed_out = True
            t_end = time.monotonic()
            self._kill_tree(proc)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

        read_out.join(timeout=5)
        read_err.join(timeout=5)
        duration_ms = int((t_end - start) * 1000)

        return ExecutionResult(
            command=command,
            exit_code=proc.returncode,
            duration_ms=duration_ms,
            stdout=_truncate(_decode_output(stdout_buf[0] if stdout_buf else b""), MAX_OUTPUT_CHARS),
            stderr=_truncate(_decode_output(stderr_buf[0] if stderr_buf else b""), MAX_OUTPUT_CHARS),
            timed_out=timed_out,
        )

    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError, PermissionError):
            pass
        finally:
            try:
                proc.kill()
            except OSError:
                pass
