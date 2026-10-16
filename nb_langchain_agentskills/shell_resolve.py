"""Which shell runs a command, and what syntax it expects — one source of truth.

``resolve_shell()`` answers two questions at once, for this package and for host
frameworks that import it (e.g. lc-agent):

1. what will *actually* execute the command (executable, flags, version), and
2. what the model must be *told* about that shell's syntax.

Keeping both answers in one function is the whole point. If the framework
resolves the shell one way and describes it another way, the agent writes
commands in the wrong syntax — e.g. it is told "PowerShell" while `cmd.exe`
runs, or it uses `&&`/`??` on Windows PowerShell 5.1 where they are syntax
errors.

``preference`` semantics ("" / "auto" = probe, anything else = pin):

  ""/"auto"       probe: a working pwsh (PowerShell 7) wins on Windows,
                  otherwise the platform default (powershell / $SHELL)
  "pwsh"          pin 7.x; if it cannot be used, fall back and say so
  "powershell"    pin 5.1 (never upgraded by probing)
  "cmd" / "bash"  pin that shell
  <path>          pin that executable

A pinned shell that cannot be used falls back to the platform default, and the
fact is reported through ``fallback_from`` — preference is a wish, probing is
the fact, and the fact is what gets reported.
"""

import base64
import locale
import os
import shutil
import subprocess
from dataclasses import dataclass, replace

PROBE_TIMEOUT_S = 5.0

# Capability flags. The guidance text is derived from these, never hard-coded
# per version string, so a new PowerShell minor release cannot stale it.
CAP_CHAIN_OPS = "chain_ops"                    # && / ||
CAP_NULL_COALESCING = "null_coalescing"        # ?? / ??=
CAP_STANDARD_ARG_PASSING = "standard_arg_passing"  # native args reach the target untouched (pwsh >= 7.3)
CAP_UTF8_OUTPUT = "utf8_output"                # output/redirect encoding defaults to UTF-8
CAP_ENCODED_COMMAND = "encoded_command"        # supports -EncodedCommand (script survives the command line verbatim)

# Prepended/appended to every PowerShell script:
#   - the progress stream is serialized as CLIXML onto stderr whenever stdout is
#     redirected (e.g. "Preparing modules for first use."), which is noise that
#     has nothing to do with the command;
#   - PowerShell does not propagate a native command's exit code by itself, so
#     without the tail a failing command reports 0.
_PS_PROGRESS_OFF = "$ProgressPreference='SilentlyContinue'; "
_PS_EXIT_TAIL = "; if ($LASTEXITCODE -is [int]) { exit $LASTEXITCODE } else { exit 0 }"

_PS_PROBE = (
    "$PSVersionTable.PSVersion.ToString(); "
    "if (Get-Variable PSNativeCommandArgumentPassing -ErrorAction SilentlyContinue) "
    "{ $PSNativeCommandArgumentPassing.ToString() } else { '' }"
)

_FLAGS: dict[str, tuple[str, ...]] = {
    "pwsh": ("-NoProfile", "-NonInteractive", "-Command"),
    "powershell": ("-NoProfile", "-NonInteractive", "-Command"),
    "cmd": ("/c",),
    "bash": ("-l", "-c"),
    "zsh": ("-l", "-c"),
    "sh": ("-c",),
}

_CACHE: dict[str, "ShellInfo"] = {}


@dataclass(frozen=True)
class ShellInfo:
    """The shell that will run commands, plus what it can do."""

    exe: str
    family: str
    args: tuple[str, ...]
    version: str = ""
    capabilities: frozenset[str] = frozenset()
    fallback_from: str | None = None

    @property
    def is_powershell(self) -> bool:
        return self.family in ("pwsh", "powershell")

    def command_prefix(self) -> list[str]:
        return [self.exe, *self.args]


def reset_shell_cache() -> None:
    """Drop cached resolutions (config reload, tests)."""
    _CACHE.clear()


def resolve_shell(preference: str = "") -> ShellInfo:
    """Resolve the shell for ``preference`` (cached per preference string)."""
    key = (preference or "").strip().lower()
    cached = _CACHE.get(key)
    if cached is None:
        cached = _resolve_uncached(preference)
        _CACHE[key] = cached
    return cached


def build_shell_command(command: str, info: ShellInfo | None = None) -> list[str]:
    """Build the argv that runs ``command`` through the resolved shell.

    On PowerShell the script is passed as ``-EncodedCommand`` (base64 UTF-16LE),
    so quotes and metacharacters inside it never take part in command-line
    parsing.
    """
    info = info or resolve_shell()
    if CAP_ENCODED_COMMAND in info.capabilities:
        script = _PS_PROGRESS_OFF + command + _PS_EXIT_TAIL
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        return [info.exe, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
    return [info.exe, *info.args, command]


def render_shell_fact(info: ShellInfo) -> str:
    """One-line fact about the resolved shell, for the system prompt."""
    label = info.family + (f" {info.version}" if info.version else "")
    if info.fallback_from:
        label += f" ({info.fallback_from} unavailable)"
    return label


def render_shell_report(info: ShellInfo) -> dict[str, str | None]:
    """Machine-readable shell fact, echoed in tool results."""
    return {
        "exe": info.exe,
        "family": info.family,
        "version": info.version,
        "fallback_from": info.fallback_from,
    }


def render_shell_guidance(info: ShellInfo) -> str:
    """Syntax guidance for the model, derived from the resolved shell.

    Every sentence here is verified against the real shell (see
    ``tests/test_shell_truth.py``) — a wrong sentence makes the model write
    commands that fail, which costs far more than the extra tokens it saves.
    Branches on ``family``/``capabilities``, never on the OS name, so a
    non-PowerShell shell configured on Windows is described correctly.
    """
    caps = info.capabilities
    if info.is_powershell:
        lines = [
            "Commands MUST use PowerShell syntax; "
            "prefer Select-Object and Select-String over head and grep.",
        ]
        if CAP_CHAIN_OPS in caps:
            lines.append("`&&` and `||` ARE supported (PowerShell 7+).")
        else:
            lines.append(
                "`&&` and `||` are NOT supported (Windows PowerShell 5.1); "
                "chain with `cmd1; if ($?) { cmd2 }` instead."
            )
        lines.append(
            "Escape with ` (backtick), not \\ — a backslash-escaped quote `\\\"` breaks the command."
        )
        lines.append(
            "Multi-line commands work as written; write a code file with a here-string "
            "@'...'@ (literal, no interpolation)."
        )
    elif info.family == "cmd":
        lines = [
            "Commands MUST use cmd.exe syntax; chain with `&&` (or `&`).",
            "A newline silently drops everything after it — put multi-line work in a .bat file.",
            'Only `"` quotes anything, and %VAR% expands even inside quotes; escape with `^`, not `\\`.',
        ]
    elif info.family in ("bash", "sh", "zsh"):
        lines = [
            "Commands MUST use bash syntax; `&&`, `||` and $VAR work as in POSIX shell.",
            'Escape with `\\` ("a \\" b" is fine); a backtick runs command substitution.',
            "Multi-line commands work as written.",
        ]
        if _is_windows():
            lines.append("On Windows this is Git Bash/MSYS: paths are MSYS-style (/c/Users/...).")
    else:
        lines = ["Unknown shell: one command per call, no `&&` chaining, no quotes inside quotes."]
    return " ".join(lines)


def decode_output(data: bytes) -> str:
    """Decode process output: UTF-8 first, then the ANSI code page / locale."""
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for encoding in _fallback_encodings():
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _is_windows() -> bool:
    return os.name == "nt"


def _platform_default_shell() -> str:
    if _is_windows():
        return "powershell"
    return os.environ.get("SHELL") or "sh"


def _resolve_exe(name: str) -> str | None:
    if os.path.isabs(name) or os.sep in name or "/" in name:
        return name if os.path.isfile(name) else None
    return shutil.which(name)


def _family_of(exe: str) -> str:
    name = os.path.basename(exe).lower()
    for suffix in (".exe", ".cmd", ".bat", ".com"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    if name.startswith("pwsh"):
        return "pwsh"
    if name.startswith("powershell"):
        return "powershell"
    if name in ("cmd", "command"):
        return "cmd"
    if name.startswith("bash"):
        return "bash"
    if name.startswith("zsh"):
        return "zsh"
    if name in ("sh", "dash", "ash"):
        return "sh"
    return "other"


def _major_minor(version: str) -> tuple[int, int]:
    parts = (version or "").split(".")
    major = minor = 0
    try:
        major = int(parts[0])
        if len(parts) > 1:
            minor = int(parts[1])
    except (ValueError, IndexError):
        pass
    return major, minor


def _probe_powershell(exe: str) -> tuple[str, str]:
    """Return (version, native_arg_passing). Empty version means "cannot run"."""
    try:
        proc = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command", _PS_PROBE],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROBE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return "", ""
    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    version = lines[0] if lines else ""
    arg_passing = lines[1] if len(lines) > 1 else ""
    return version, arg_passing


def _probe_bash(exe: str) -> str:
    try:
        proc = subprocess.run(
            [exe, "-c", 'printf %s "$BASH_VERSION"'],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROBE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""
    return (proc.stdout or "").strip()


def _capabilities(family: str, version: str, arg_passing: str) -> frozenset[str]:
    caps: set[str] = set()
    major, _minor = _major_minor(version)
    if family == "pwsh":
        caps |= {CAP_ENCODED_COMMAND, CAP_UTF8_OUTPUT}
        if major >= 7:
            caps |= {CAP_CHAIN_OPS, CAP_NULL_COALESCING}
        # Only trust the probed setting: PowerShell 7.3 flipped the default to
        # "Standard", but a machine can still run in "Windows" mode (measured:
        # 7.6.7 with "Windows"), so a version-based guess would over-promise.
        if arg_passing.strip().lower() == "standard":
            caps.add(CAP_STANDARD_ARG_PASSING)
    elif family == "powershell":
        # 5.1: no && / || / ??, native args re-quoted, console code page output.
        caps.add(CAP_ENCODED_COMMAND)
    elif family == "cmd":
        caps.add(CAP_CHAIN_OPS)
    elif family in ("bash", "sh", "zsh"):
        caps |= {CAP_CHAIN_OPS, CAP_UTF8_OUTPUT}
    return frozenset(caps)


def _try_shell(name: str) -> ShellInfo | None:
    """Resolve one shell, validating that it really starts. None when unusable.

    ``shutil.which`` is not enough on Windows: pwsh is often an ``WindowsApps``
    app-execution alias, which resolves but can still fail to launch from a
    service/non-interactive process. So the PowerShell probe doubles as the
    launch check.
    """
    exe = _resolve_exe(name)
    if exe is None:
        return None
    family = _family_of(exe)
    args = _FLAGS.get(family, ("-c",))
    if family in ("pwsh", "powershell"):
        version, arg_passing = _probe_powershell(exe)
        if not version:
            return None
        return ShellInfo(
            exe=exe,
            family=family,
            args=args,
            version=version,
            capabilities=_capabilities(family, version, arg_passing),
        )
    tail = ["/c", "exit 0"] if family == "cmd" else ["-c", "exit 0"]
    try:
        proc = subprocess.run(
            [exe, *tail], capture_output=True, timeout=PROBE_TIMEOUT_S
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if proc.returncode != 0:
        return None
    version = _probe_bash(exe) if family in ("bash", "zsh") else ""
    return ShellInfo(
        exe=exe,
        family=family,
        args=args,
        version=version,
        capabilities=_capabilities(family, version, ""),
    )


def _resolve_uncached(preference: str) -> ShellInfo:
    pref = (preference or "").strip()
    if pref and pref.lower() != "auto":
        pinned = _try_shell(pref)
        if pinned is not None:
            return pinned
        fallback_name = _platform_default_shell()
        fallback = _try_shell(fallback_name)
        if fallback is not None:
            return replace(fallback, fallback_from=pref)
        return _unvalidated_fallback(fallback_name, fallback_from=pref)

    # "" / "auto": a working PowerShell 7 wins on Windows, else platform default.
    candidate = "pwsh" if _is_windows() else _platform_default_shell()
    probed = _try_shell(candidate)
    if probed is not None:
        return probed
    fallback_name = _platform_default_shell()
    if fallback_name == candidate:
        return _unvalidated_fallback(fallback_name)
    fallback = _try_shell(fallback_name)
    if fallback is not None:
        return replace(fallback, fallback_from=candidate)
    return _unvalidated_fallback(fallback_name, fallback_from=candidate)


def _unvalidated_fallback(name: str, fallback_from: str | None = None) -> ShellInfo:
    """Last resort: report the platform default even if it did not validate.

    Reporting an unvalidated shell beats reporting a shell we know nothing
    about: the guidance still matches what the OS will run, and the execution
    error (if any) surfaces normally.
    """
    family = _family_of(name)
    return ShellInfo(
        exe=name,
        family=family,
        args=_FLAGS.get(family, ("-c",)),
        fallback_from=fallback_from,
    )


def _fallback_encodings() -> list[str]:
    encodings: list[str] = []
    if _is_windows():
        encodings.append("mbcs")
        # ``mbcs`` maps to the ANSI code page, which is UTF-8 (cp65001) when the
        # "Beta: use UTF-8" option is on — then mbcs cannot decode legacy output.
        # Chinese Windows tools still print GBK, so keep one concrete fallback.
        encodings.append("gbk")
    preferred = locale.getpreferredencoding(False)
    if preferred and preferred.lower() not in ("utf-8", "cp65001"):
        encodings.append(preferred)
    return encodings
