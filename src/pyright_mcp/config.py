from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .models import FindConfigResultModel


def _has_pyright_section_in_pyproject(pyproject_path: Path) -> bool:
    try:
        text = pyproject_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    # Minimal check: look for a [tool.pyright] section header
    return re.search(r"(?m)^\s*\[tool\.pyright\]\s*$", text) is not None


def find_pyright_config(start_dir: str | Path | None) -> FindConfigResultModel:
    """
    Search upward from start_dir for Pyright configuration.
    Preference order:
      1) pyrightconfig.json
      2) pyproject.toml with [tool.pyright]
    Stops at filesystem root.
    """
    if start_dir is None:
        start = Path.cwd()
    else:
        start = Path(start_dir)

    start = start.resolve()
    cur: Optional[Path] = start

    while cur is not None:
        pyright_json = cur / "pyrightconfig.json"
        if pyright_json.is_file():
            return FindConfigResultModel(
                found=True,
                config_path=str(pyright_json),
                kind="pyrightconfig.json",
                resolve_dir=str(cur),
                searched_from=str(start),
            )

        pyproject = cur / "pyproject.toml"
        if pyproject.is_file() and _has_pyright_section_in_pyproject(pyproject):
            return FindConfigResultModel(
                found=True,
                config_path=str(pyproject),
                kind="pyproject.toml",
                resolve_dir=str(cur),
                searched_from=str(start),
            )

        # ascend
        parent = cur.parent
        if parent == cur:
            break
        cur = parent

    # Not found
    return FindConfigResultModel(
        found=False,
        config_path=None,
        kind=None,
        resolve_dir=str(start),
        searched_from=str(start),
    )