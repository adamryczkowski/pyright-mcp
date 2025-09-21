from __future__ import annotations

import subprocess
from pathlib import Path

from pyright_mcp.config import find_pyright_config
from pyright_mcp.runner import PyrightRunner, PyrightCheckParams


def test_find_config_prefers_pyrightconfig_json(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    # Both files exist, pyrightconfig.json should win
    (root / "pyrightconfig.json").write_text("{}", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        """
[tool.pyright]
include = ["src"]
        """.strip(),
        encoding="utf-8",
    )

    res = find_pyright_config(str(root))
    assert res.found is True
    assert res.kind == "pyrightconfig.json"
    assert res.config_path and res.config_path.endswith("pyrightconfig.json")
    assert res.resolve_dir == str(root.resolve())


def test_find_config_pyproject_when_section_present(tmp_path: Path) -> None:
    root = tmp_path / "proj2"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        """
[project]
name = "x"

[tool.pyright]
typeCheckingMode = "standard"
        """.strip(),
        encoding="utf-8",
    )
    res = find_pyright_config(str(root))
    assert res.found is True
    assert res.kind == "pyproject.toml"
    assert res.config_path and res.config_path.endswith("pyproject.toml")
    assert res.resolve_dir == str(root.resolve())


def test_find_config_not_found(tmp_path: Path) -> None:
    root = tmp_path / "no-config"
    root.mkdir()
    res = find_pyright_config(str(root))
    assert res.found is False
    assert res.config_path is None
    assert res.kind is None
    assert res.resolve_dir == str(root.resolve())


def test_runner_timeout_path(tmp_path: Path, monkeypatch) -> None:
    # Arrange: create a minimal directory
    target = tmp_path / "p"
    target.mkdir()

    # Monkeypatch subprocess.run in our module to raise TimeoutExpired
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=kwargs.get("args") or args[0], timeout=0.001)

    monkeypatch.setattr("pyright_mcp.runner.subprocess.run", fake_run)

    runner = PyrightRunner()
    params = PyrightCheckParams(target=str(target), timeout_sec=1)
    out = runner.run_check(params)
    assert out["ok"] is False
    assert out["exit_code"] == -1
    assert "timeout" in (out["fail_reason"] or "").lower()