from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


Severity = Literal["information", "warning", "error"]
FailOn = Literal["none", "information", "warning", "error"]


class RangePosModel(BaseModel):
    line: int
    character: int


class RangeModel(BaseModel):
    start: RangePosModel
    end: RangePosModel


class DiagnosticModel(BaseModel):
    file: str
    range: RangeModel
    severity: Severity
    severity_level: int = Field(description="Normalized: information=1, warning=2, error=3")
    code: Optional[str] = None
    rule: Optional[str] = None
    message: str


class SummaryModel(BaseModel):
    files_analyzed: int
    error_count: int
    warning_count: int
    information_count: int
    time_sec: float


class PyrightCheckResultModel(BaseModel):
    ok: bool
    fail_reason: Optional[str] = None
    command: list[str]
    exit_code: int
    summary: SummaryModel
    diagnostics: list[DiagnosticModel]
    pyright_version: str
    analyzed_root: str
    checked_paths: list[str]
    venv_path: Optional[str] = None


class PyrightVersionResultModel(BaseModel):
    version: str
    executable_path: str
    supports_outputjson: bool


class FindConfigResultModel(BaseModel):
    found: bool
    config_path: Optional[str] = None
    kind: Optional[Literal["pyrightconfig.json", "pyproject.toml", "unknown"]] = None
    resolve_dir: str
    searched_from: str