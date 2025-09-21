from __future__ import annotations

import json
import re
import shutil
import subprocess
import os
import sys
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple, TypedDict, cast

Severity = Literal["information", "warning", "error"]
FailOn = Literal["none", "information", "warning", "error"]

SEVERITY_LEVEL: Dict[Severity, int] = {
    "information": 1,
    "warning": 2,
    "error": 3,
}


class RangePos(TypedDict):
    line: int
    character: int


class Range(TypedDict):
    start: RangePos
    end: RangePos


class DiagnosticOutRequired(TypedDict):
    file: str
    range: Range
    severity: Severity
    severity_level: int
    message: str


class DiagnosticOut(DiagnosticOutRequired, total=False):
    code: str | None
    rule: str | None


class SummaryOut(TypedDict):
    files_analyzed: int
    error_count: int
    warning_count: int
    information_count: int
    time_sec: float


class VersionInfo(TypedDict):
    version: str
    executable_path: str
    supports_outputjson: bool


class CheckResult(TypedDict):
    ok: bool
    fail_reason: str | None
    command: List[str]
    exit_code: int
    summary: SummaryOut
    diagnostics: List[DiagnosticOut]
    pyright_version: str
    analyzed_root: str
    checked_paths: List[str]
    venv_path: str


@dataclass(frozen=True)
class PyrightCheckParams:
    """Input parameters for a Pyright check invocation."""

    target: str = "."
    cwd: Optional[str] = None
    include: Optional[List[str]] = None
    exclude: Optional[List[str]] = None
    extra_args: Optional[List[str]] = None
    timeout_sec: int = 60
    fail_on_severity: FailOn = "none"


def parse_pyright_json(text: str) -> Optional[dict[str, Any]]:
    """
    Attempt to parse Pyright JSON output; return None on failure.

    Expected structure:
      {
        "version": "...",
        "time": "...",
        "generalDiagnostics": [...],
        "summary": {
          "filesAnalyzed": number,
          "errorCount": number,
          "warningCount": number,
          "informationCount": number,
          "timeInSec": number
        }
      }
    """
    try:
        obj = json.loads(text)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    if "summary" not in obj or "generalDiagnostics" not in obj:
        return None
    return obj


def _parse_version_string(s: str) -> str:
    # pyright --version outputs like: "pyright 1.1.405"
    m = re.search(r"\b(\d+\.\d+\.\d+)\b", s)
    return m.group(1) if m else s.strip()


def _supports_outputjson(version: str) -> bool:
    # --outputjson has existed for years; conservatively assume True if a semver appears.
    return bool(re.match(r"^\d+\.\d+\.\d+$", version))


def _detect_venv_path() -> str:
    """
    Best-effort detection of the active Python environment path used for libraries.

    Priority:
      1) $VIRTUAL_ENV if set
      2) sys.prefix when it differs from sys.base_prefix (virtual environment)
      3) sys.prefix (base interpreter) as a stable fallback
    """
    env = os.environ.get("VIRTUAL_ENV")
    if env:
        try:
            return str(Path(env).resolve())
        except Exception:
            return env
    try:
        if getattr(sys, "prefix", "") and getattr(sys, "base_prefix", "") and sys.prefix != sys.base_prefix:
            return str(Path(sys.prefix).resolve())
    except Exception:
        pass
    # Fallback: always provide a path (mandatory contract)
    try:
        return str(Path(sys.prefix).resolve())
    except Exception:
        # Extremely unlikely; fallback to current working directory to keep contract
        return str(Path.cwd())


def _build_pyright_argv() -> Tuple[List[str], str]:
    """
    Resolve how to invoke pyright.

    Returns:
      (argv_prefix, display_exe)
      - argv_prefix: e.g. ["/path/to/pyright"] or [sys.executable, "-m", "pyright"]
      - display_exe: human-readable command identifier used in VersionInfo.executable_path
    """
    exe = shutil.which("pyright")
    if exe:
        return [exe], exe
    # Fallback to Python module invocation if available
    try:
        cp = subprocess.run(
            [sys.executable, "-m", "pyright", "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if cp.returncode == 0 and cp.stdout:
            return [sys.executable, "-m", "pyright"], f"{sys.executable} -m pyright"
    except Exception:
        pass
    return [], ""

def get_pyright_version() -> VersionInfo:
    argv, display = _build_pyright_argv()
    if not argv:
        return VersionInfo(version="", executable_path="", supports_outputjson=False)
    try:
        cp = subprocess.run(
            [*argv, "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        ver = _parse_version_string(cp.stdout or "")
        return VersionInfo(version=ver, executable_path=display or argv[0], supports_outputjson=_supports_outputjson(ver))
    except Exception:
        return VersionInfo(version="", executable_path=display or (argv[0] if argv else ""), supports_outputjson=False)


def _iter_included_paths(root: Path, include: Optional[List[str]], exclude: Optional[List[str]]) -> List[Path]:
    """
    Expand include globs relative to root, filter exclude globs.
    If include is None, return [root].
    """
    if include:
        found: set[Path] = set()
        for pat in include:
            for p in root.glob(pat):
                if p.is_file():
                    found.add(p.resolve())
                elif p.is_dir():
                    for f in p.rglob("*"):
                        if f.is_file():
                            found.add(f.resolve())
        paths = list(found)
    else:
        paths = [root.resolve()]

    if exclude:
        relroot = root.resolve()
        filtered: List[Path] = []
        for p in paths:
            try:
                rel = p.resolve().relative_to(relroot)
                rel_posix = str(rel).replace("\\", "/")
            except ValueError:
                rel_posix = p.name
            name = p.name
            if any(fnmatch(rel_posix, ex) or fnmatch(name, ex) for ex in exclude):
                continue
            filtered.append(p)
        return filtered
    return paths


def _normalize_diag(d: dict[str, Any]) -> DiagnosticOut:
    file = str(d.get("file", ""))
    sev_raw = d.get("severity", "information")
    sev: Severity = sev_raw if sev_raw in ("information", "warning", "error") else "information"
    rng = cast(dict[str, Any], d.get("range") or {})
    start = cast(dict[str, Any], rng.get("start") or {})
    end = cast(dict[str, Any], rng.get("end") or {})
    norm: DiagnosticOut = {
        "file": str(Path(file).resolve()),
        "range": {
            "start": {"line": int(start.get("line", 0)), "character": int(start.get("character", 0))},
            "end": {"line": int(end.get("line", 0)), "character": int(end.get("character", 0))},
        },
        "severity": sev,
        "severity_level": SEVERITY_LEVEL[sev],
        "message": str(d.get("message", "")),
    }
    rule_val = d.get("rule")
    norm["rule"] = str(rule_val) if isinstance(rule_val, str) else None
    norm["code"] = norm["rule"]
    return norm


def _compute_threshold_ok(diags: Iterable[DiagnosticOut], threshold: FailOn) -> Tuple[bool, Optional[str]]:
    if threshold == "none":
        return True, None
    th_val = {"information": 1, "warning": 2, "error": 3}[threshold]
    max_sev = 0
    for d in diags:
        max_sev = max(max_sev, d["severity_level"])
        if max_sev >= th_val:
            break
    if max_sev >= th_val and max_sev > 0:
        msg = f"fail_on_severity '{threshold}' breached (max_severity_level={max_sev})."
        return False, msg
    return True, None


class PyrightRunner:
    """
    Execute Pyright with JSON output and normalize results for automated tooling.
    """

    def run_check(self, params: PyrightCheckParams) -> CheckResult:
        venv_path = _detect_venv_path()
        target_path = Path(params.target)
        if not target_path.exists():
            analyzed_root = (Path(params.cwd) if params.cwd else target_path.parent).resolve()
            return CheckResult(
                ok=False,
                fail_reason=f"Target path not found: {target_path}",
                command=[],
                exit_code=4,
                summary=SummaryOut(
                    files_analyzed=0,
                    error_count=0,
                    warning_count=0,
                    information_count=0,
                    time_sec=0.0,
                ),
                diagnostics=[],
                pyright_version=get_pyright_version().get("version", ""),
                analyzed_root=str(analyzed_root),
                checked_paths=[],
                venv_path=venv_path,
            )

        # Determine analysis root
        if params.cwd:
            analyzed_root = Path(params.cwd).resolve()
        else:
            analyzed_root = target_path.resolve() if target_path.is_dir() else target_path.parent.resolve()

        # Prepare list of paths we will check (what we pass to Pyright)
        if target_path.is_dir():
            root_for_globs_checked = target_path.resolve()
        else:
            root_for_globs_checked = target_path.parent.resolve()
        paths_for_checked = _iter_included_paths(root_for_globs_checked, params.include, params.exclude)
        if params.include:
            checked_paths = [str(p) for p in sorted(set(paths_for_checked))]
        else:
            checked_paths = [str(target_path.resolve())]

        version_info = get_pyright_version()
        argv_prefix, display_exe = _build_pyright_argv()
        if not argv_prefix:
            return CheckResult(
                ok=False,
                fail_reason=(
                    "Pyright not available (neither 'pyright' executable nor 'python -m pyright'). "
                    "Install via pipx: 'pipx install pyright-mcp' (bundles pyright), "
                    "or add pyright to your environment."
                ),
                command=[],
                exit_code=-1,
                summary=SummaryOut(
                    files_analyzed=0,
                    error_count=0,
                    warning_count=0,
                    information_count=0,
                    time_sec=0.0,
                ),
                diagnostics=[],
                pyright_version="",
                analyzed_root=str(analyzed_root),
                checked_paths=checked_paths,
                venv_path=venv_path,
            )

        # Build invocation
        argv: List[str] = [*argv_prefix, "--outputjson"]
        if params.extra_args:
            argv.extend(params.extra_args)

        # Expand include/exclude if provided
        if target_path.is_dir():
            root_for_globs = target_path.resolve()
        else:
            root_for_globs = target_path.parent.resolve()

        paths: List[Path] = _iter_included_paths(root_for_globs, params.include, params.exclude)

        # If include specified, pass explicit files; else pass target directly
        if params.include:
            path_args = [str(p) for p in sorted(set(paths))]
        else:
            path_args = [str(target_path.resolve())]

        cmd = argv + path_args

        try:
            cp = subprocess.run(
                cmd,
                cwd=str(analyzed_root),
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=params.timeout_sec,
            )
        except subprocess.TimeoutExpired:
            return CheckResult(
                ok=False,
                fail_reason=(
                    f"Timeout after {params.timeout_sec}s while running Pyright. "
                    "Try increasing timeout_sec, reducing include scope, or enabling Pyright caching."
                ),
                command=cmd,
                exit_code=-1,
                summary=SummaryOut(
                    files_analyzed=0,
                    error_count=0,
                    warning_count=0,
                    information_count=0,
                    time_sec=0.0,
                ),
                diagnostics=[],
                pyright_version=version_info["version"],
                analyzed_root=str(analyzed_root),
                checked_paths=checked_paths,
                venv_path=venv_path,
            )
        except FileNotFoundError:
            # Race or PATH issue during subprocess spawning
            return CheckResult(
                ok=False,
                fail_reason="Failed to execute Pyright. Ensure 'pyright' is installed and on PATH.",
                command=cmd,
                exit_code=-1,
                summary=SummaryOut(
                    files_analyzed=0,
                    error_count=0,
                    warning_count=0,
                    information_count=0,
                    time_sec=0.0,
                ),
                diagnostics=[],
                pyright_version=version_info["version"],
                analyzed_root=str(analyzed_root),
                checked_paths=checked_paths,
                venv_path=venv_path,
            )

        raw_output = cp.stdout or ""
        parsed = parse_pyright_json(raw_output)
        if parsed is None:
            # Include tail of stdout/stderr for debugging
            tail = (raw_output + "\n" + (cp.stderr or "")).strip()
            tail_excerpt = tail[-1000:] if len(tail) > 1000 else tail
            return CheckResult(
                ok=False,
                fail_reason=(
                    "Failed to parse Pyright JSON output. Consider upgrading Pyright or "
                    "checking CLI arguments. Output tail:\n" + tail_excerpt
                ),
                command=cmd,
                exit_code=cp.returncode,
                summary=SummaryOut(
                    files_analyzed=0,
                    error_count=0,
                    warning_count=0,
                    information_count=0,
                    time_sec=0.0,
                ),
                diagnostics=[],
                pyright_version=version_info["version"],
                analyzed_root=str(analyzed_root),
                checked_paths=checked_paths,
                venv_path=venv_path,
            )

        # Normalize diagnostics
        diags_raw = cast(list[dict[str, Any]], parsed.get("generalDiagnostics", []) or [])
        diags: List[DiagnosticOut] = [_normalize_diag(d) for d in diags_raw]
        diags.sort(key=lambda d: (d["file"], d["range"]["start"]["line"], d["range"]["start"]["character"]))

        # Normalize summary
        summary_raw = cast(dict[str, Any], parsed.get("summary", {}) or {})
        summary: SummaryOut = SummaryOut(
            files_analyzed=int(summary_raw.get("filesAnalyzed", 0)),
            error_count=int(summary_raw.get("errorCount", 0)),
            warning_count=int(summary_raw.get("warningCount", 0)),
            information_count=int(summary_raw.get("informationCount", 0)),
            time_sec=float(summary_raw.get("timeInSec", 0.0)),
        )

        ok, reason = _compute_threshold_ok(diags, params.fail_on_severity)

        result: CheckResult = CheckResult(
            ok=ok,
            fail_reason=reason,
            command=cmd,
            exit_code=cp.returncode,
            summary=summary,
            diagnostics=diags,
            pyright_version=str(parsed.get("version") or version_info["version"]),
            analyzed_root=str(analyzed_root),
            checked_paths=checked_paths,
            venv_path=venv_path,
        )
        return result