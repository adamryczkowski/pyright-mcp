from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from .config import find_pyright_config as do_find_config
from .models import (
    FailOn,
    FindConfigResultModel,
    PyrightCheckResultModel,
    PyrightVersionResultModel,
    DiagnosticModel,
    SummaryModel,
    RangeModel,
    RangePosModel,
)
from .runner import CheckResult, PyrightCheckParams, PyrightRunner, get_pyright_version


mcp = FastMCP("Pyright MCP Server")


class PyrightCheckInput(BaseModel):
    target: str = Field(default=".", description="File or directory to analyze")
    cwd: Optional[str] = Field(default=None, description="Working directory to run from")
    include: Optional[list[str]] = Field(
        default=None, description="Glob patterns to include, resolved relative to cwd/target"
    )
    exclude: Optional[list[str]] = Field(default=None, description="Glob patterns to exclude from analysis set")
    extra_args: Optional[list[str]] = Field(
        default=None, description="Additional Pyright CLI args, e.g. ['--pythonversion','3.12']"
    )
    timeout_sec: int = Field(default=60, ge=1, description="Timeout in seconds")
    fail_on_severity: FailOn = Field(
        default="none",
        description="Threshold to mark ok=false when diagnostics at or above this severity are present",
    )


@mcp.tool()
def pyright_version() -> PyrightVersionResultModel:
    """
    Return pyright CLI version info and resolved executable path.
    """
    info = get_pyright_version()
    return PyrightVersionResultModel(
        version=info["version"],
        executable_path=info["executable_path"],
        supports_outputjson=info["supports_outputjson"],
    )


@mcp.tool()
def find_pyright_config(start_dir: str | None = None) -> FindConfigResultModel:
    """
    Discover the configuration file used by Pyright starting from start_dir (or CWD if omitted).
    """
    return do_find_config(start_dir)


@mcp.tool()
def pyright_check(
    target: str,
    cwd: str | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    extra_args: list[str] | None = None,
    timeout_sec: int = 60,
    fail_on_severity: FailOn = "none",
) -> PyrightCheckResultModel:
    """
    Run Pyright with JSON output and return normalized, structured diagnostics.
    """
    runner = PyrightRunner()
    params = PyrightCheckParams(
        target=target,
        cwd=cwd,
        include=include,
        exclude=exclude,
        extra_args=extra_args,
        timeout_sec=timeout_sec,
        fail_on_severity=fail_on_severity,
    )
    out: CheckResult = runner.run_check(params)

    summary_model = SummaryModel(
        files_analyzed=out["summary"]["files_analyzed"],
        error_count=out["summary"]["error_count"],
        warning_count=out["summary"]["warning_count"],
        information_count=out["summary"]["information_count"],
        time_sec=out["summary"]["time_sec"],
    )

    diagnostics_models = [
        DiagnosticModel(
            file=d["file"],
            range=RangeModel(
                start=RangePosModel(**d["range"]["start"]),
                end=RangePosModel(**d["range"]["end"]),
            ),
            severity=d["severity"],
            severity_level=d["severity_level"],
            code=d.get("code"),
            rule=d.get("rule"),
            message=d["message"],
        )
        for d in out["diagnostics"]
    ]

    return PyrightCheckResultModel(
        ok=out["ok"],
        fail_reason=out["fail_reason"],
        command=[str(x) for x in out["command"]],
        exit_code=out["exit_code"],
        summary=summary_model,
        diagnostics=diagnostics_models,
        pyright_version=out["pyright_version"],
        analyzed_root=out["analyzed_root"],
        checked_paths=[str(p) for p in out["checked_paths"]],
        venv_path=out["venv_path"],
    )


def main() -> None:
    # Run the FastMCP server over stdio (default transport for direct execution)
    mcp.run()


if __name__ == "__main__":
    main()