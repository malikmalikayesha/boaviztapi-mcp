"""Start the real entry point over stdio and list the tools (no network needed)."""

import os
import sys

import mcp
import pytest
from mcp.client.stdio import StdioServerParameters, stdio_client

pytestmark = pytest.mark.anyio


async def test_entry_point_serves_tools_over_stdio() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "boaviztapi_mcp"],
        env={**os.environ, "BOAVIZTAPI_URL": "http://127.0.0.1:9"},
    )
    async with mcp.Client(stdio_client(params)) as client:
        assert client.server_info is not None
        assert client.server_info.name == "boaviztapi"
        tools = (await client.list_tools()).tools
        assert len(tools) == 8
        result = await client.call_tool("list_impact_criteria", {})
        assert result.is_error
        assert "did not respond" in result.content[0].text  # type: ignore[union-attr]
