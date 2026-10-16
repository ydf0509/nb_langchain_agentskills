"""shell_resolve：唯一真相源的解析、能力、命令构造与提示词。

全部用例都是 hermetic 的：探测（which / 版本子进程）都被打桩，不依赖跑测试的这台机器
装了什么 shell。唯一的真实依赖是 cache 的清理。
"""

import base64

import pytest

from nb_langchain_agentskills import shell_resolve as sr


@pytest.fixture(autouse=True)
def _clear_cache():
    sr.reset_shell_cache()
    yield
    sr.reset_shell_cache()


def _fake_which(mapping: dict[str, str]):
    def _which(name: str) -> str | None:
        return mapping.get(name)

    return _which


def _patch_powershell(monkeypatch, version: str, arg_passing: str = "") -> None:
    monkeypatch.setattr(sr, "_probe_powershell", lambda exe: (version, arg_passing))


def _patch_posix(monkeypatch, *, exe_returns: dict[str, str], version: str = "5.2.0") -> None:
    monkeypatch.setattr(sr, "_is_windows", lambda: False)
    monkeypatch.setattr(sr, "_resolve_exe", lambda name: exe_returns.get(name))

    class _Proc:
        returncode = 0

    monkeypatch.setattr(sr.subprocess, "run", lambda *a, **k: _Proc())
    monkeypatch.setattr(sr, "_probe_bash", lambda exe: version)


# --- 解析 -------------------------------------------------------------------

def test_auto_prefers_pwsh_on_windows(monkeypatch):
    monkeypatch.setattr(sr, "_is_windows", lambda: True)
    monkeypatch.setattr(sr.shutil, "which", _fake_which({"pwsh": r"C:\fake\pwsh.exe"}))
    _patch_powershell(monkeypatch, "7.6.7", "Standard")

    info = sr.resolve_shell("")

    assert info.family == "pwsh"
    assert info.version == "7.6.7"
    assert info.fallback_from is None
    assert {"chain_ops", "null_coalescing", "standard_arg_passing", "utf8_output"} <= info.capabilities


def test_auto_falls_back_when_pwsh_missing(monkeypatch):
    monkeypatch.setattr(sr, "_is_windows", lambda: True)
    monkeypatch.setattr(
        sr.shutil, "which", _fake_which({"powershell": r"C:\fake\powershell.exe"})
    )
    _patch_powershell(monkeypatch, "5.1.22621.6133")

    info = sr.resolve_shell("")

    assert info.family == "powershell"
    assert info.fallback_from == "pwsh"
    assert "chain_ops" not in info.capabilities
    assert "null_coalescing" not in info.capabilities


def test_pwsh_that_resolves_but_cannot_launch_is_rejected(monkeypatch):
    """Windows 上 pwsh 常是 WindowsApps 的 app-execution alias：
    which 找得到，但服务/非交互进程里起不来，探测必须实跑。"""
    monkeypatch.setattr(sr, "_is_windows", lambda: True)
    monkeypatch.setattr(
        sr.shutil,
        "which",
        _fake_which({"pwsh": r"C:\alias\pwsh.exe", "powershell": r"C:\fake\powershell.exe"}),
    )
    monkeypatch.setattr(
        sr, "_probe_powershell", lambda exe: ("", "") if "pwsh" in exe else ("5.1.6718", "")
    )

    info = sr.resolve_shell("")

    assert info.family == "powershell"
    assert info.fallback_from == "pwsh"


def test_pinned_shell_is_never_upgraded(monkeypatch):
    monkeypatch.setattr(sr, "_is_windows", lambda: True)
    monkeypatch.setattr(sr.shutil, "which", _fake_which({"pwsh": r"C:\fake\pwsh.exe"}))
    _patch_powershell(monkeypatch, "7.6.7", "Standard")

    info = sr.resolve_shell("powershell")

    assert info.family == "powershell"


def test_pinned_unavailable_records_fallback(monkeypatch):
    monkeypatch.setattr(sr, "_is_windows", lambda: True)
    monkeypatch.setattr(
        sr.shutil, "which", _fake_which({"powershell": r"C:\fake\powershell.exe"})
    )
    _patch_powershell(monkeypatch, "5.1.6718")

    info = sr.resolve_shell("nosuchshell")

    assert info.family == "powershell"
    assert info.fallback_from == "nosuchshell"
    assert "(nosuchshell unavailable)" in sr.render_shell_fact(info)


def test_pinned_cmd(monkeypatch):
    monkeypatch.setattr(sr, "_is_windows", lambda: True)
    monkeypatch.setattr(sr.shutil, "which", _fake_which({"cmd": r"C:\fake\cmd.exe"}))

    class _Proc:
        returncode = 0

    monkeypatch.setattr(sr.subprocess, "run", lambda *a, **k: _Proc())

    info = sr.resolve_shell("cmd")

    assert info.family == "cmd"
    assert info.args == ("/c",)
    assert "chain_ops" in info.capabilities


def test_posix_bash(monkeypatch):
    _patch_posix(monkeypatch, exe_returns={"/bin/bash": "/bin/bash"})
    monkeypatch.setenv("SHELL", "/bin/bash")

    info = sr.resolve_shell("")

    assert info.family == "bash"
    assert info.args == ("-l", "-c")
    assert {"chain_ops", "utf8_output"} <= info.capabilities


def test_probe_failure_keeps_conservative_capabilities(monkeypatch):
    monkeypatch.setattr(sr, "_is_windows", lambda: True)
    monkeypatch.setattr(
        sr.shutil,
        "which",
        _fake_which({"pwsh": r"C:\fake\pwsh.exe", "powershell": r"C:\fake\powershell.exe"}),
    )
    monkeypatch.setattr(
        sr, "_probe_powershell", lambda exe: ("", "") if "pwsh" in exe else ("", "")
    )

    info = sr.resolve_shell("")

    # 两个都探测失败：仍然如实报告平台默认，但能力取保守子集
    assert info.capabilities == frozenset()
    assert "NOT supported" in sr.render_shell_guidance(info)


def test_capabilities_follow_the_probed_arg_passing_setting(monkeypatch):
    """实测：pwsh 7.6.7 的 $PSNativeCommandArgumentPassing 可以是 "Windows"，
    所以不能按版本号推测"标准传递"，只能信探测值。"""
    monkeypatch.setattr(sr, "_is_windows", lambda: True)
    monkeypatch.setattr(sr.shutil, "which", _fake_which({"pwsh": r"C:\fake\pwsh.exe"}))

    _patch_powershell(monkeypatch, "7.6.7", "Windows")
    assert "standard_arg_passing" not in sr.resolve_shell("").capabilities

    sr.reset_shell_cache()
    _patch_powershell(monkeypatch, "7.6.7", "Standard")
    assert "standard_arg_passing" in sr.resolve_shell("").capabilities


def test_resolution_is_cached(monkeypatch):
    monkeypatch.setattr(sr, "_is_windows", lambda: True)
    monkeypatch.setattr(sr.shutil, "which", _fake_which({"pwsh": r"C:\fake\pwsh.exe"}))
    calls: list[str] = []

    def _probe(exe: str) -> tuple[str, str]:
        calls.append(exe)
        return "7.6.7", "Standard"

    monkeypatch.setattr(sr, "_probe_powershell", _probe)

    first = sr.resolve_shell("")
    second = sr.resolve_shell("")

    assert first is second
    assert calls == [r"C:\fake\pwsh.exe"]


# --- 命令构造 ---------------------------------------------------------------

def test_powershell_command_is_encoded(monkeypatch):
    monkeypatch.setattr(sr, "_is_windows", lambda: True)
    monkeypatch.setattr(
        sr.shutil,
        "which",
        _fake_which({"powershell": r"C:\fake\powershell.exe"}),
    )
    _patch_powershell(monkeypatch, "5.1.6718")

    info = sr.resolve_shell("")
    argv = sr.build_shell_command('Write-Output "a ""q"" b"', info)

    assert argv[0] == r"C:\fake\powershell.exe"
    assert "-EncodedCommand" in argv
    script = base64.b64decode(argv[-1]).decode("utf-16-le")
    assert 'Write-Output "a ""q"" b"' in script
    assert "$ProgressPreference" in script
    assert "$LASTEXITCODE" in script


def test_cmd_command_is_plain(monkeypatch):
    monkeypatch.setattr(sr, "_is_windows", lambda: True)
    monkeypatch.setattr(sr.shutil, "which", _fake_which({"cmd": r"C:\fake\cmd.exe"}))

    class _Proc:
        returncode = 0

    monkeypatch.setattr(sr.subprocess, "run", lambda *a, **k: _Proc())

    info = sr.resolve_shell("cmd")

    assert sr.build_shell_command("dir", info) == [r"C:\fake\cmd.exe", "/c", "dir"]


# --- 提示词 -----------------------------------------------------------------

def _info(family: str, version: str = "", caps: tuple[str, ...] = ()) -> sr.ShellInfo:
    return sr.ShellInfo(
        exe=f"{family}.exe", family=family, args=(), version=version, capabilities=frozenset(caps)
    )


def test_guidance_mentions_missing_operators_on_5_1():
    text = sr.render_shell_guidance(_info("powershell", "5.1.22621.6133"))
    assert "NOT supported" in text
    assert "ARE supported" not in text


def test_guidance_mentions_operators_on_7():
    text = sr.render_shell_guidance(_info("pwsh", "7.6.7", ("chain_ops", "null_coalescing")))
    assert "ARE supported" in text


def test_guidance_for_cmd_is_not_powershell(monkeypatch):
    """回归：以前 Windows 上无论配什么 shell 都说 PowerShell（os_name == "Windows" 恒真）。"""
    monkeypatch.setattr(sr, "_is_windows", lambda: True)
    text = sr.render_shell_guidance(_info("cmd", "", ("chain_ops",)))
    assert "cmd.exe" in text
    assert "PowerShell syntax" not in text


def test_guidance_does_not_over_warn_about_nested_quotes():
    """实测（pwsh 7.6.7）：`he said "hi"`、`"C:\\dir\\"`、`a;b|c` 都原样到达目标程序，
    所以不该再写 "avoid nested quotes" 这种过度警告 —— 它会白绕道去写脚本文件。"""
    text = sr.render_shell_guidance(_info("pwsh", "7.6.7", ("chain_ops",)))

    assert "avoid nested quotes" not in text
    assert "Native arguments" not in text


def test_guidance_does_not_mention_null_coalescing():
    """`??` 是表达式层的空值合并，不是命令链运算符，不进提示词。"""
    assert "??" not in sr.render_shell_guidance(_info("pwsh", "7.6.7", ("chain_ops",)))
    assert "??" not in sr.render_shell_guidance(_info("powershell", "5.1.22621.6133"))


def test_guidance_always_recommends_script_files():
    for family in ("pwsh", "powershell", "cmd", "bash", "other"):
        assert "script file" in sr.render_shell_guidance(_info(family))


# --- 解码 -------------------------------------------------------------------

def test_decode_output_falls_back_to_gbk(monkeypatch):
    """系统 ANSI 代码页是 UTF-8 时 mbcs 不管用，中文 Windows 的 GBK 输出仍要能读。"""
    monkeypatch.setattr(sr, "_is_windows", lambda: True)
    raw = "中文输出".encode("gbk")
    assert sr.decode_output(raw) == "中文输出"


def test_decode_output_prefers_utf8():
    assert sr.decode_output("中文".encode("utf-8")) == "中文"
    assert sr.decode_output(b"") == ""
