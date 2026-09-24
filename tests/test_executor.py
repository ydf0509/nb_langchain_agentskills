import os
import sys

import pytest

from nb_langchain_agentskills.executor import CommandExecutor, _decode_output


def run_py(tmp_path, code, **kwargs):
    path = tmp_path / "probe.py"
    path.write_text(code, encoding="utf-8")
    exe = sys.executable
    if os.name == "nt":
        command = f'& "{exe}" "{path}"'
    else:
        command = f'"{exe}" "{path}"'
    return executor_run(command, tmp_path, **kwargs)


def executor_run(command, cwd, **kwargs):
    return CommandExecutor().run(command, cwd=cwd, **kwargs)


def test_success_structure(tmp_path):
    result = run_py(tmp_path, "print(42)")
    assert result.exit_code == 0
    assert result.timed_out is False
    assert "42" in result.stdout
    text = result.to_text()
    assert "exit_code: 0" in text
    assert "duration_ms:" in text
    assert "stdout:" in text
    assert "stderr:" in text


def test_non_zero_exit_returns_output(tmp_path):
    result = run_py(tmp_path, 'import sys; print("boom"); sys.exit(3)')
    assert result.exit_code == 3
    assert "boom" in result.stdout


def test_stderr_captured(tmp_path):
    result = run_py(tmp_path, 'import sys; sys.stderr.write("warn")')
    assert "warn" in result.stderr


def test_timeout_kills_tree(tmp_path):
    code = 'import time; print("started", flush=True); time.sleep(10)'
    result = run_py(tmp_path, code, timeout_ms=1000)
    assert result.timed_out is True
    assert "started" in result.stdout


def test_pythonpath_prepended(tmp_path):
    code = 'import os; print(os.environ.get("PYTHONPATH", ""))'
    result = run_py(
        tmp_path, code, pythonpath_dirs=[tmp_path, tmp_path / "scripts"]
    )
    assert str(tmp_path) in result.stdout
    assert str(tmp_path / "scripts") in result.stdout


def test_pythonpath_disabled(tmp_path):
    code = 'import os; print(os.environ.get("PYTHONPATH", ""))'
    executor = CommandExecutor(enable_pythonpath=False)
    result = executor.run(
        run_command_for(tmp_path), cwd=tmp_path, pythonpath_dirs=[tmp_path]
    )
    assert str(tmp_path) not in result.stdout


def run_command_for(directory):
    path = directory / "probe2.py"
    path.write_text('import os; print(os.environ.get("PYTHONPATH", ""))', encoding="utf-8")
    exe = sys.executable
    if os.name == "nt":
        return f'& "{exe}" "{path}"'
    return f'"{exe}" "{path}"'


def test_validations(tmp_path):
    executor = CommandExecutor()
    with pytest.raises(ValueError):
        executor.run("", cwd=tmp_path)
    with pytest.raises(ValueError):
        executor.run("echo hi", cwd=tmp_path, timeout_ms=0)


def test_duration_excludes_kill_wait(tmp_path):
    code = 'import time; print("started", flush=True); time.sleep(10)'
    result = run_py(tmp_path, code, timeout_ms=800)
    assert result.timed_out is True
    assert result.duration_ms < 2000


def test_windows_embedded_quotes(tmp_path):
    if os.name != "nt":
        pytest.skip("powershell-specific quoting")
    result = CommandExecutor().run('Write-Output "a ""q"" b"', cwd=tmp_path)
    assert 'a "q" b' in result.stdout


def test_decode_output_utf8_passthrough():
    assert _decode_output("héllo".encode("utf-8")) == "héllo"


def test_decode_output_mbcs_fallback():
    if os.name != "nt":
        pytest.skip("mbcs codec is Windows-only")
    gbk_bytes = "你好".encode("mbcs")
    assert _decode_output(gbk_bytes) == "你好"


def test_decode_output_replaces_undecodable():
    assert _decode_output(b"\xff\xff\xff") == "\ufffd\ufffd\ufffd"
