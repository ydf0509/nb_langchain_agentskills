"""真值测试：提示词里的每一条 shell 事实，都对着真实 shell 跑一遍。

提示词只允许写这里能证明成立的话（跑不到的 shell 直接 skip）。
"""

import subprocess

import pytest

from nb_langchain_agentskills import (
    build_shell_command,
    decode_output,
    reset_shell_cache,
    resolve_shell,
)


@pytest.fixture(autouse=True)
def _fresh_shell_cache():
    reset_shell_cache()
    yield
    reset_shell_cache()


def _require(preference: str, family: str):
    """该 shell 必须真的可用（没被回退），否则跳过。"""
    info = resolve_shell(preference)
    if info.family != family or info.fallback_from:
        pytest.skip(
            f"{preference} 不可用（实际 {info.family}, fallback_from={info.fallback_from}）"
        )
    return info


def _run(preference: str, command: str, timeout: int = 40):
    info = resolve_shell(preference)
    proc = subprocess.run(
        build_shell_command(command, info), capture_output=True, timeout=timeout
    )
    return proc.returncode, decode_output(proc.stdout) + decode_output(proc.stderr)


# --- pwsh 7 -----------------------------------------------------------------

def test_pwsh_multi_line_works():
    _require("pwsh", "pwsh")
    rc, out = _run("pwsh", "echo one\necho two")
    assert rc == 0 and "one" in out and "two" in out


def test_pwsh_chains_with_and_or():
    _require("pwsh", "pwsh")
    rc, out = _run("pwsh", "echo one && echo two")
    assert rc == 0 and "one" in out and "two" in out


def test_pwsh_backtick_escapes_and_backslash_does_not():
    """提示词写的是：用反引号转义，`\\"` 会打断命令。"""
    _require("pwsh", "pwsh")
    rc, out = _run("pwsh", 'echo "a`"b"')
    assert rc == 0 and 'a"b' in out

    rc_backslash, _ = _run("pwsh", 'echo "a \\"b"')
    assert rc_backslash != 0


def test_pwsh_here_string_is_literal():
    _require("pwsh", "pwsh")
    rc, out = _run("pwsh", "$x = @'\n$HOME `n\n'@\n$x")
    assert rc == 0 and "$HOME" in out and "`n" in out


# --- Windows PowerShell 5.1 -------------------------------------------------

def test_powershell_5_1_chaining_fails_but_if_last_exit_code_works():
    """提示词写的是：5.1 不支持 &&/||，用 `cmd1; if ($?) { cmd2 }` 代替。"""
    _require("powershell", "powershell")
    rc, _ = _run("powershell", "echo one && echo two")
    assert rc != 0

    rc_chain, out = _run("powershell", "echo one; if ($?) { echo two }")
    assert rc_chain == 0 and "one" in out and "two" in out


# --- cmd --------------------------------------------------------------------

def test_cmd_newline_truncates_silently():
    """提示词写的是：cmd 里换行会静默丢掉后面的内容。"""
    _require("cmd", "cmd")
    rc, out = _run("cmd", "echo one\necho two")
    assert rc == 0
    assert "one" in out
    assert "two" not in out


def test_cmd_ampersand_chains():
    _require("cmd", "cmd")
    _, out = _run("cmd", "echo one & echo two")
    assert "one" in out and "two" in out


def test_cmd_expands_percent_vars_even_inside_quotes():
    """提示词写的是：%VAR% 在引号内也会展开（而且没有单引号字符串）。"""
    _require("cmd", "cmd")
    _, quoted = _run("cmd", 'echo "%OS%"')
    assert "Windows_NT" in quoted

    _, single = _run("cmd", "echo '%OS%'")
    assert "Windows_NT" in single


# --- bash（POSIX；Windows 上通常是 Git Bash） -------------------------------

def test_bash_escape_style_and_backtick_substitution():
    """提示词写的是：bash 用 `\\` 转义，反引号是命令替换。"""
    _require("bash", "bash")
    rc, out = _run("bash", 'echo "a \\" b"')
    assert rc == 0 and 'a " b' in out

    rc_sub, out_sub = _run("bash", "echo `echo substituted`")
    assert rc_sub == 0 and "substituted" in out_sub
