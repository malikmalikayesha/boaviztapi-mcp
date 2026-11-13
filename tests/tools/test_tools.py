"""Every tool, called through the MCP SDK's in-memory client."""

from collections.abc import AsyncIterator
from typing import Any

import mcp
import pytest

from boaviztapi_mcp.config import Settings
from boaviztapi_mcp.server import create_server
from tests.replay import ReplayTransport

pytestmark = pytest.mark.anyio

TOOLS = {
    "list_impact_criteria",
    "search_catalog",
    "describe_catalog_item",
    "estimate_cloud_instance",
    "estimate_server",
    "estimate_component",
    "estimate_device",
    "compare_estimates",
}


@pytest.fixture
async def session() -> AsyncIterator[mcp.Client]:
    server = create_server(Settings(), transport=ReplayTransport())
    async with mcp.Client(server) as client:
        yield client


async def call(session: mcp.Client, name: str, args: dict[str, Any]) -> Any:
    result = await session.call_tool(name, args)
    assert not result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content


async def error(session: mcp.Client, name: str, args: dict[str, Any]) -> str:
    result = await session.call_tool(name, args)
    assert result.is_error
    return result.content[0].text  # type: ignore[union-attr]


async def test_tools_are_listed_with_schemas_and_annotations(
    session: mcp.Client,
) -> None:
    tools = {tool.name: tool for tool in (await session.list_tools()).tools}
    assert set(tools) == TOOLS
    for tool in tools.values():
        assert tool.description
        assert tool.output_schema is not None
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.title
        assert tool.annotations.title == tool.title
        assert tool.annotations.destructive_hint is False
    schema = tools["search_catalog"].input_schema
    assert schema["required"] == ["kind"]
    assert "gpu" in str(schema["properties"]["kind"])


async def test_server_identity(session: mcp.Client) -> None:
    assert session.server_info is not None
    assert session.server_info.name == "boaviztapi"
    assert session.instructions is not None
    assert "not available from BoaviztAPI" in session.instructions


async def test_list_impact_criteria(session: mcp.Client) -> None:
    result = await call(session, "list_impact_criteria", {"query": "water"})
    codes = [c["code"] for c in result["criteria"]]
    assert codes[0] == "wu"
    assert all("water" in c["description"].lower() for c in result["criteria"])
    assert result["summary"].startswith("wu: Use of water resources (m3 eq.)")


async def test_search_catalog(session: mcp.Client) -> None:
    result = await call(session, "search_catalog", {"kind": "gpu", "query": "h100"})
    assert result["total_matches"] == 3
    assert result["summary"].startswith("3 gpu matches: NVIDIA H100")


async def test_describe_catalog_item(session: mcp.Client) -> None:
    result = await call(
        session,
        "describe_catalog_item",
        {"kind": "cloud_instance", "name": "m5.xlarge", "provider": "aws"},
    )
    assert result["name"] == "aws m5.xlarge"
    assert result["details"]["vcpu"] == 4
    assert "platform: m5.metal" in result["summary"]


async def test_estimate_cloud_instance(session: mcp.Client) -> None:
    result = await call(
        session,
        "estimate_cloud_instance",
        {
            "provider": "aws",
            "instance_type": "m5.xlarge",
            "usage_location": "FRA",
            "duration_hours": 730,
        },
    )
    assert result["subject"]["name"] == "aws m5.xlarge"
    assert result["location"]["code"] == "FRA"
    assert [i["criterion"] for i in result["impacts"]] == ["gwp", "adp", "pe"]


async def test_estimate_server(session: mcp.Client) -> None:
    result = await call(
        session,
        "estimate_server",
        {
            "cpu": {"name": "xeon gold 6134", "units": 2},
            "ram": [{"units": 12, "capacity_gb": 32}],
            "usage_location": "France",
            "duration_hours": 43800,
            "detail": "breakdown",
        },
    )
    assert result["duration"]["exceeds_lifetime"] is True
    assert result["breakdown"]


async def test_estimate_component(session: mcp.Client) -> None:
    result = await call(
        session,
        "estimate_component",
        {
            "component": "gpu",
            "name": "h100 sxm",
            "units": 4,
            "usage_location": "Germany",
            "duration_hours": 8760,
        },
    )
    assert result["summary"].startswith("4x NVIDIA H100 SXM 80GB, over 8760 h")
    assert result["impacts"][0]["total"]["value"] == 7867


async def test_estimate_device(session: mcp.Client) -> None:
    result = await call(session, "estimate_device", {"device_type": "laptop"})
    assert result["impacts"][0]["embedded"]["value"] == 181


async def test_compare_estimates(session: mcp.Client) -> None:
    result = await call(
        session,
        "compare_estimates",
        {
            "items": [
                {
                    "label": "France",
                    "kind": "cloud_instance",
                    "params": {
                        "provider": "aws",
                        "instance_type": "m5.xlarge",
                        "usage_location": "FRA",
                    },
                },
                {
                    "label": "United States",
                    "kind": "cloud_instance",
                    "params": {
                        "provider": "aws",
                        "instance_type": "m5.xlarge",
                        "usage_location": "USA",
                    },
                },
            ],
            "duration_hours": 730,
        },
    )
    assert result["comparison"][0]["lowest"] == "France"
    assert len(result["results"]) == 2


async def test_domain_errors_are_tool_errors(session: mcp.Client) -> None:
    text = await error(session, "estimate_device", {"device_type": "iot_device"})
    assert "iot_device needs an archetype" in text
    assert "smart_watch" in text

    text = await error(
        session, "estimate_component", {"component": "gpu", "criteria": ["all"]}
    )
    assert "list_impact_criteria" in text


async def test_compare_params_are_validated(session: mcp.Client) -> None:
    text = await error(
        session,
        "compare_estimates",
        {
            "items": [
                {"label": "a", "kind": "device", "params": {"device_type": "laptop"}},
                {"label": "b", "kind": "device", "params": {"device": "laptop"}},
            ],
            "duration_hours": 8760,
        },
    )
    assert "Item 'b' (device)" in text
    assert "device_type" in text


async def test_schema_violations_are_rejected(session: mcp.Client) -> None:
    text = await error(session, "estimate_component", {"component": "gpu", "units": 0})
    assert "units" in text
