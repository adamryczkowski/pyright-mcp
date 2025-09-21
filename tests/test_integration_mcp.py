from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.asyncio
async def test_server_integration_std_io(tmp_path: Path) -> None:
    # Create a tiny project with one file containing an error to exercise diagnostics
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "bad.py").write_text(
        "def f(x: int) -> int:\n    return 'not-int'\n", encoding="utf-8"
    )

    # Spawn our server via Poetry console script
    server_params = StdioServerParameters(
        command="poetry",
        args=["run", "pyright-mcp-server"],
        env={},
    )

    # Connect client over stdio and exercise the tools
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}
            assert {"pyright_check", "pyright_version", "find_pyright_config"}.issubset(tool_names)

            # Call version tool
            ver = await session.call_tool("pyright_version", {})
            assert hasattr(ver, "structuredContent")
            assert ver.structuredContent is not None
            v = cast(dict[str, Any], ver.structuredContent)
            assert isinstance(v.get("version"), str)

            # Call check tool on our temporary project
            res = await session.call_tool(
                "pyright_check",
                {"target": str(proj)},
            )
            assert hasattr(res, "structuredContent")
            assert res.structuredContent is not None
            payload = cast(dict[str, Any], res.structuredContent)
            assert payload.get("pyright_version")
            assert isinstance(payload.get("diagnostics"), list)
            # Should have at least one error
            assert payload["summary"]["error_count"] >= 1
            assert any(d["severity"] == "error" for d in payload["diagnostics"])