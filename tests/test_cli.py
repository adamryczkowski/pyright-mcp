from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from pyright_mcp.cli import main as cli_main


def test_cli_runs_and_outputs_json(tmp_path: Path) -> None:
    proj = tmp_path / "p1"
    proj.mkdir()
    (proj / "ok.py").write_text("x: int = 1\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli_main, [str(proj)])
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    assert isinstance(payload, dict)
    assert "summary" in payload
    assert "diagnostics" in payload
    assert payload.get("ok") in (True, False)
    assert isinstance(payload.get("venv_path"), str) and payload["venv_path"]


def test_cli_exit_code_flips_on_threshold(tmp_path: Path) -> None:
    proj = tmp_path / "p2"
    proj.mkdir()
    # intentional type error
    (proj / "bad.py").write_text("def f(x: int) -> int:\n    return 'oops'\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli_main, [str(proj), "--fail-on-severity", "error"])
    # Expect nonzero exit because there is at least one error and threshold=error
    assert result.exit_code == 1, result.output

    payload = json.loads(result.output)
    assert payload.get("ok") is False
    assert payload["summary"]["error_count"] >= 1