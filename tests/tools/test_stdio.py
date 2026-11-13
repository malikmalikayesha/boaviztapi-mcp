"""Start the real entry point over stdio and list the tools (no network needed)."""

import json
import os
import subprocess
import sys
from typing import Any

import mcp
import pytest
from mcp.client.stdio import StdioServerParameters, stdio_client


@pytest.mark.anyio
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


# Raw JSON-RPC over stdio: checks the wire format of both protocol generations.

MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "tests", "version": "0"},
}


def exchange(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    env = {**os.environ, "BOAVIZTAPI_URL": "http://127.0.0.1:9"}
    process = subprocess.Popen(
        [sys.executable, "-m", "boaviztapi_mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    replies = []
    try:
        for message in messages:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
            if "id" in message:
                replies.append(json.loads(process.stdout.readline()))
    finally:
        process.stdin.close()
        process.wait(timeout=10)
    return replies


def test_stateless_protocol_2026_07_28() -> None:
    discover, tools = exchange(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "server/discover",
                "params": {"_meta": MODERN_META},
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {"_meta": MODERN_META},
            },
        ]
    )
    result = discover["result"]
    assert "2026-07-28" in result["supportedVersions"]
    assert result["resultType"] == "complete"
    assert result["capabilities"]["tools"] == {"listChanged": False}
    assert result["instructions"]

    listing = tools["result"]
    assert listing["resultType"] == "complete"
    assert listing["ttlMs"] == 86_400_000
    assert listing["cacheScope"] == "public"
    server_info = listing["_meta"]["io.modelcontextprotocol/serverInfo"]
    assert server_info["name"] == "boaviztapi"
    assert server_info["description"]
    names = [tool["name"] for tool in listing["tools"]]
    assert len(names) == 8
    assert all(tool["title"] for tool in listing["tools"])


def test_handshake_protocol_2025_11_25() -> None:
    initialize, tools = exchange(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "tests", "version": "0"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
    )
    assert initialize["result"]["protocolVersion"] == "2025-11-25"
    assert initialize["result"]["serverInfo"]["title"] == "BoaviztAPI"
    assert len(tools["result"]["tools"]) == 8
