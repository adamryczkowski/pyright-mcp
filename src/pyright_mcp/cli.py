from __future__ import annotations

import json
import sys
from typing import Optional, cast

import click

from .runner import FailOn, PyrightCheckParams, PyrightRunner


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("target", required=False, default=".")
@click.option(
    "--cwd",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=str),
    default=None,
    help="Working directory to run from",
)
@click.option(
    "--include",
    "include_patterns",
    multiple=True,
    help="Glob to include (repeatable). Resolved under the target root",
)
@click.option(
    "--exclude",
    "exclude_patterns",
    multiple=True,
    help="Glob to exclude (repeatable). Filters the include set",
)
@click.option(
    "--extra-arg",
    "extra_args",
    multiple=True,
    help="Pass-through CLI arg to Pyright (repeatable), e.g. --extra-arg --pythonversion --extra-arg 3.12",
)
@click.option(
    "--timeout-sec",
    type=int,
    default=60,
    show_default=True,
    help="Timeout in seconds for Pyright subprocess",
)
@click.option(
    "--fail-on-severity",
    type=click.Choice(["none", "information", "warning", "error"], case_sensitive=False),
    default="none",
    show_default=True,
    help="Flip exit code to 1 if any diagnostic meets/exceeds this level",
)
def main(
    target: str,
    cwd: Optional[str],
    include_patterns: tuple[str, ...],
    exclude_patterns: tuple[str, ...],
    extra_args: tuple[str, ...],
    timeout_sec: int,
    fail_on_severity: str,
) -> None:
    """
    Run Pyright via the pyright-mcp runner and print JSON to stdout.

    Exit code: 0 if ok=true, 1 if ok=false (threshold or infrastructure failure).
    """
    runner = PyrightRunner()

    fail_choice = fail_on_severity.lower()
    fail_val = cast(FailOn, fail_choice)

    params = PyrightCheckParams(
        target=target,
        cwd=cwd,
        include=list(include_patterns) if include_patterns else None,
        exclude=list(exclude_patterns) if exclude_patterns else None,
        extra_args=list(extra_args) if extra_args else None,
        timeout_sec=timeout_sec,
        fail_on_severity=fail_val,
    )

    result = runner.run_check(params)
    # Deterministic JSON output
    click.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()