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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_MS = 180_000
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
    """Execute skill commands with timeout, process-tree kill and truncation.
    流式输出的
    """

    def __init__(self, *, enable_pythonpath: bool = True) -> None:
        self.enable_pythonpath = enable_pythonpath

    def run(
        self,
        command: str,
        *,
        cwd: Path,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        pythonpath_dirs: list[Path] | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> ExecutionResult:
        """Run a command and wait for it to finish.

        When ``on_output`` is given it is called from the calling thread
        with each decoded stdout/stderr chunk as soon as it arrives, so
        callers can forward live output (e.g. via LangChain custom events)
        instead of waiting for the process to exit. Both streams share one
        channel in arrival order. Callback errors are swallowed so
        streaming never breaks the run.
        """
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

        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        # stdout and stderr merged in arrival order for live streaming.
        stream_chunks: list[bytes] = []
        buf_lock = threading.Lock()

        def _pump(stream, sink: list[bytes]) -> None:
            try:
                while True:
                    line = stream.readline()
                    if not line:
                        break
                    with buf_lock:
                        sink.append(line)
                        stream_chunks.append(line)
            except (ValueError, OSError):
                pass
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        def _emit(chunk: bytes) -> None:
            if on_output is None:
                return
            try:
                on_output(_decode_output(chunk))
            except Exception:
                pass

        read_out = threading.Thread(target=_pump, args=(proc.stdout, stdout_chunks), daemon=True)
        read_err = threading.Thread(target=_pump, args=(proc.stderr, stderr_chunks), daemon=True)
        read_out.start()
        read_err.start()

        # Poll in the calling thread so on_output fires with the caller's
        # context (e.g. LangChain parent run id for custom events).
        timed_out = False
        deadline = start + timeout_ms / 1000
        emitted = 0
        t_end = start
        while True:
            with buf_lock:
                pending = stream_chunks[emitted:]
                exited = proc.poll() is not None
            if pending:
                emitted += len(pending)
                _emit(b"".join(pending))
            if exited:
                t_end = time.monotonic()
                break
            now = time.monotonic()
            if now >= deadline:
                timed_out = True
                t_end = now
                self._kill_tree(proc)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                break
            time.sleep(0.2)

        read_out.join(timeout=5)
        read_err.join(timeout=5)
        with buf_lock:
            remaining = stream_chunks[emitted:]
            stdout_data = b"".join(stdout_chunks)
            stderr_data = b"".join(stderr_chunks)
        if remaining:
            _emit(b"".join(remaining))
        duration_ms = int((t_end - start) * 1000)

        return ExecutionResult(
            command=command,
            exit_code=proc.returncode,
            duration_ms=duration_ms,
            stdout=_truncate(_decode_output(stdout_data), MAX_OUTPUT_CHARS),
            stderr=_truncate(_decode_output(stderr_data), MAX_OUTPUT_CHARS),
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
