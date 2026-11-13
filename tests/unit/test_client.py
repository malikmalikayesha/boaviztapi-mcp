import asyncio
import json
from collections.abc import Callable

import httpx2
import pytest

from boaviztapi_mcp.client import MAX_CONCURRENCY, USER_AGENT, BoaviztaClient
from boaviztapi_mcp.config import Settings
from boaviztapi_mcp.errors import (
    UnexpectedResponse,
    UpstreamError,
    UpstreamNotFound,
    UpstreamServerError,
    UpstreamUnavailable,
    UpstreamValidationError,
)

pytestmark = pytest.mark.anyio

Handler = Callable[[httpx2.Request], httpx2.Response]


def make_client(handler: Handler, **settings: object) -> BoaviztaClient:
    return BoaviztaClient(
        Settings(**settings),  # type: ignore[arg-type]
        transport=httpx2.MockTransport(handler),
        retry_delay=0,
    )


async def test_sends_user_agent_and_query_params() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"ok": True})

    client = make_client(handler, base_url="http://api.test")
    result = await client.post(
        "/v1/component/gpu",
        [("criteria", "gwp"), ("criteria", "pe"), ("verbose", "true")],
        {"units": 2},
    )

    assert result == {"ok": True}
    request = seen[0]
    assert request.headers["user-agent"] == USER_AGENT
    assert str(request.url).startswith("http://api.test/v1/component/gpu?")
    assert request.url.params.get_list("criteria") == ["gwp", "pe"]
    assert json.loads(request.content) == {"units": 2}


async def test_maps_404_detail() -> None:
    client = make_client(
        lambda _: httpx2.Response(404, json={"detail": "nope at aws not found"})
    )
    with pytest.raises(UpstreamNotFound) as exc:
        await client.get("/v1/cloud/instance/instance_config")
    assert exc.value.detail == "nope at aws not found"


async def test_maps_422_field_errors() -> None:
    body = {
        "detail": [
            {
                "type": "int_parsing",
                "loc": ["body", "capacity"],
                "msg": "Input should be a valid integer",
                "input": "lots",
            }
        ]
    }
    client = make_client(lambda _: httpx2.Response(422, json=body))
    with pytest.raises(UpstreamValidationError) as exc:
        await client.post("/v1/component/ram", [], {"capacity": "lots"})
    assert exc.value.problems == ["capacity: Input should be a valid integer"]


async def test_500_is_not_retried() -> None:
    calls = 0

    def handler(_: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(500, text="Internal Server Error")

    client = make_client(handler)
    with pytest.raises(UpstreamServerError) as exc:
        await client.post("/v1/component/gpu", [], {})
    assert exc.value.status == 500
    assert calls == 1


async def test_503_is_retried_once() -> None:
    responses = [httpx2.Response(503), httpx2.Response(200, json=[1])]
    client = make_client(lambda _: responses.pop(0))
    assert await client.get("/v1/utils/gpu_name") == [1]
    assert responses == []


async def test_gives_up_after_second_503() -> None:
    client = make_client(lambda _: httpx2.Response(503, text="busy"))
    with pytest.raises(UpstreamServerError) as exc:
        await client.get("/v1/utils/gpu_name")
    assert exc.value.status == 503


async def test_connection_errors_are_retried_then_reported() -> None:
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        raise httpx2.ConnectError("refused", request=request)

    client = make_client(handler, base_url="http://localhost:5000", timeout=3)
    with pytest.raises(UpstreamUnavailable) as exc:
        await client.get("/v1/utils/version")
    assert calls == 2
    assert "http://localhost:5000" in str(exc.value)
    assert "docker run" in str(exc.value)


async def test_timeouts_are_reported() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    client = make_client(handler)
    with pytest.raises(UpstreamUnavailable, match="timed out"):
        await client.get("/v1/utils/version")


async def test_other_4xx_and_non_json_bodies() -> None:
    client = make_client(lambda _: httpx2.Response(405, text="Method Not Allowed"))
    with pytest.raises(UpstreamError, match="HTTP 405"):
        await client.get("/v1/utils/version")

    client = make_client(lambda _: httpx2.Response(200, text="<html>"))
    with pytest.raises(UnexpectedResponse):
        await client.get("/v1/utils/version")


async def test_lookups_are_cached() -> None:
    calls = 0

    def handler(_: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(200, json=["aws"])

    client = make_client(handler)
    for _ in range(3):
        assert await client.get("/v1/cloud/instance/all_providers") == ["aws"]
    assert calls == 1


async def test_estimates_are_cached_per_body() -> None:
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(200, json=json.loads(request.content))

    client = make_client(handler)
    assert await client.post("/v1/component/gpu", [], {"units": 1}) == {"units": 1}
    assert await client.post("/v1/component/gpu", [], {"units": 1}) == {"units": 1}
    assert await client.post("/v1/component/gpu", [], {"units": 2}) == {"units": 2}
    assert calls == 2


async def test_cache_can_be_disabled() -> None:
    calls = 0

    def handler(_: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(200, json="2.6.0")

    client = make_client(handler, cache_ttl=0)
    assert await client.version() == "2.6.0"
    assert await client.version() == "2.6.0"
    assert calls == 2


async def test_concurrency_is_capped() -> None:
    running = 0
    peak = 0

    async def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return httpx2.Response(200, json=request.url.params["n"])

    client = BoaviztaClient(Settings(), transport=httpx2.MockTransport(handler))
    results = await asyncio.gather(
        *(client.get("/v1/utils/x", [("n", str(i))]) for i in range(12))
    )
    assert results == [str(i) for i in range(12)]
    assert peak == MAX_CONCURRENCY
    await client.aclose()
