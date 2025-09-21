import os
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from pyright_mcp.runner import FailOn


# Tests target the runner API that we'll implement in src/pyright_mcp/runner.py
# The tests are designed to be fast and hermetic using temp dirs.


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.mark.parametrize("with_error", [False, True])
def test_runner_basic(tmp_path: Path, with_error: bool) -> None:
    # Arrange: create a tiny sample project
    src = tmp_path / "proj"
    src.mkdir()
    code_ok = """
from __future__ import annotations

def add(a: int, b: int) -> int:
    return a + b

x = add(1, 2)
""".strip()

    code_err = """
from __future__ import annotations

def add(a: int, b: int) -> int:
    return a + b

y: str = add(1, 2)  # type error on purpose
""".strip()

    write(src / "a.py", code_ok)
    if with_error:
        write(src / "b.py", code_err)

    # Act
    from pyright_mcp.runner import PyrightRunner, PyrightCheckParams

    runner = PyrightRunner()
    params = PyrightCheckParams(
        target=str(src),
        cwd=None,
        include=None,
        exclude=None,
        extra_args=None,
        timeout_sec=60,
        fail_on_severity="none",
    )
    result = runner.run_check(params)

    # Assert summary fields exist and are ints
    summary = result["summary"]
    assert isinstance(summary["files_analyzed"], int)
    assert isinstance(summary["error_count"], int)
    assert isinstance(summary["warning_count"], int)
    assert isinstance(summary["information_count"], int)
    assert isinstance(summary["time_sec"], (int, float))

    # Assert version and command present
    assert isinstance(result["pyright_version"], str)
    assert isinstance(result["command"], list)
    assert isinstance(result["exit_code"], int)

    # Diagnostics determinism: sorted by (file, start.line, start.character)
    diags = result["diagnostics"]
    assert isinstance(diags, list)
    sorted_diags = sorted(
        diags,
        key=lambda d: (d["file"], d["range"]["start"]["line"], d["range"]["start"]["character"]),
    )
    assert diags == sorted_diags

    # Severity normalization
    for d in diags:
        assert d["severity"] in {"error", "warning", "information"}
        assert d["severity_level"] in {1, 2, 3}

    # If with_error we expect at least one error; otherwise zero errors
    if with_error:
        assert summary["error_count"] >= 1
        assert any(d["severity"] == "error" for d in diags)
        assert result["ok"] is True  # threshold is none
    else:
        assert summary["error_count"] == 0
        assert not any(d["severity"] == "error" for d in diags)
        assert result["ok"] is True


def test_include_exclude_filtering(tmp_path: Path) -> None:
    # Arrange: create files where one should be excluded via pattern
    root = tmp_path / "proj2"
    root.mkdir()
    write(root / "included.py", "a: int = 1\n")
    write(root / "excluded.py", "b: str = 123  # error\n")

    from pyright_mcp.runner import PyrightRunner, PyrightCheckParams

    runner = PyrightRunner()
    params = PyrightCheckParams(
        target=str(root),
        cwd=None,
        include=["**/*.py"],
        exclude=["excluded.py"],  # exclude one file
        extra_args=None,
        timeout_sec=60,
        fail_on_severity="none",
    )
    result = runner.run_check(params)

    # Expect no errors since excluded.py should be filtered out
    assert result["summary"]["error_count"] == 0
    assert all(d["file"].endswith("included.py") for d in result["diagnostics"])


def test_nonexistent_target_returns_helpful_error(tmp_path: Path) -> None:
    missing = tmp_path / "nope" / "missing.py"

    from pyright_mcp.runner import PyrightRunner, PyrightCheckParams

    runner = PyrightRunner()
    params = PyrightCheckParams(
        target=str(missing),
        cwd=None,
        include=None,
        exclude=None,
        extra_args=None,
        timeout_sec=10,
        fail_on_severity="none",
    )
    result = runner.run_check(params)
    assert result["ok"] is False
    assert "not found" in (result.get("fail_reason") or "").lower()


def test_parse_json_failure_yields_actionable_error() -> None:
    # Use the pure function to validate parsing behavior
    from pyright_mcp.runner import parse_pyright_json

    bad = "not-json"
    parsed = parse_pyright_json(bad)
    assert parsed is None  # signifies failure


def test_pyright_version_available() -> None:
    from pyright_mcp.runner import get_pyright_version

    ver = get_pyright_version()
    # On this machine pyright should be installed; verify minimal structure
    assert isinstance(ver["version"], str) and ver["version"]
    assert isinstance(ver["executable_path"], str) and ver["executable_path"]
    assert ver["supports_outputjson"] is True


@pytest.mark.parametrize(
    "threshold,expect_ok",
    [
        ("none", True),
        ("information", True),  # any info or higher will flip ok if diagnostics exist
        ("warning", True),       # no warnings in clean file
        ("error", True),         # no errors in clean file
    ],
)
def test_fail_on_severity_threshold(tmp_path: Path, threshold: FailOn, expect_ok: bool) -> None:
    # Use a file that produces information-level diagnostics (often none by default).
    # We'll ensure behavior is deterministic: if no diagnostics, ok remains True.
    root = tmp_path / "proj3"
    root.mkdir()
    write(root / "c.py", "z = 1\n")

    from pyright_mcp.runner import PyrightRunner, PyrightCheckParams

    runner = PyrightRunner()
    params = PyrightCheckParams(
        target=str(root),
        cwd=None,
        include=None,
        exclude=None,
        extra_args=None,
        timeout_sec=60,
        fail_on_severity=threshold,
    )
    result = runner.run_check(params)

    # If there are no diagnostics at or above threshold, ok True; otherwise False
    assert isinstance(result["ok"], bool)
    if threshold == "information" and len(result["diagnostics"]) > 0:
        # If any diagnostics exist, information threshold will flip ok to False
        assert result["ok"] is False
    else:
        assert result["ok"] is expect_ok


def test_pyright_not_found_error_message(monkeypatch) -> None:
    # Simulate pyright being unavailable both as an executable and as a Python module.
    from pyright_mcp import runner as r

    monkeypatch.setattr(r.shutil, "which", lambda name: None)

    def fake_run(*args: Any, **kwargs: Any):
        # Make any attempt to invoke "python -m pyright" fail
        raise FileNotFoundError("pyright not available")

    monkeypatch.setattr(r.subprocess, "run", fake_run)

    info = r.get_pyright_version()
    assert info["version"] == ""
    assert info["executable_path"] == ""
    assert info["supports_outputjson"] is False