"""Checks against a real BoaviztAPI. Opt in with ``pytest -m live``.

Set BOAVIZTAPI_URL (for example http://localhost:5000 with the Docker image).
The quirk tests describe the behaviour we would *like* upstream to have. They are
strict xfails: when upstream fixes a quirk the test passes, strict mode turns that
into a failure, and the workaround in this project can be reviewed and removed.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import httpx2
import pytest

from boaviztapi_mcp.client import BoaviztaClient
from boaviztapi_mcp.config import Settings
from boaviztapi_mcp.models import ComparisonResult, EstimateResult
from tests import scenarios

pytestmark = [pytest.mark.live, pytest.mark.anyio]

BASE_URL = os.environ.get("BOAVIZTAPI_URL", "").rstrip("/")


@pytest.fixture(scope="module")
def base_url() -> str:
    if not BASE_URL:
        pytest.skip("BOAVIZTAPI_URL is not set")
    return BASE_URL


@pytest.fixture
async def live_client(base_url: str) -> AsyncIterator[BoaviztaClient]:
    client = BoaviztaClient(Settings(base_url=base_url, timeout=60))
    yield client
    await client.aclose()


@pytest.fixture(scope="module")
def http(base_url: str) -> Iterator[httpx2.Client]:
    with httpx2.Client(base_url=base_url, timeout=60) as client:
        yield client


ESTIMATE_SCENARIOS = [n for n in scenarios.SCENARIOS if not n.startswith("catalog_")]


@pytest.mark.parametrize("name", ESTIMATE_SCENARIOS)
async def test_scenarios_return_sane_results(
    live_client: BoaviztaClient, name: str
) -> None:
    result = await scenarios.SCENARIOS[name](live_client)
    items = result.results if isinstance(result, ComparisonResult) else [result]
    for item in items:
        assert isinstance(item, EstimateResult)
        assert item.impacts
        assert any(i.embedded.status == "ok" for i in item.impacts)
        assert item.api.version
        assert item.summary.endswith(item.api.base_url)


async def test_catalog_scenarios_run(live_client: BoaviztaClient) -> None:
    await scenarios.catalog_lists(live_client)
    await scenarios.catalog_details(live_client)


async def test_gpu_criteria_fallback_still_returns_gwp(
    live_client: BoaviztaClient,
) -> None:
    result = await scenarios.gpu_with_failing_criterion(live_client)
    gwp = result.impacts[0]
    assert gwp.criterion == "gwp"
    assert gwp.embedded.status == "ok"


# Known upstream quirks -------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="unknown criteria return 500, not 4xx")
def test_quirk_unknown_criterion_is_a_client_error(http: httpx2.Client) -> None:
    response = http.post("/v1/component/cpu", params={"criteria": "bogus"}, json={})
    assert 400 <= response.status_code < 500


@pytest.mark.xfail(strict=True, reason="criteria=all returns 500 (KeyError: 'all')")
def test_quirk_criteria_all_works(http: httpx2.Client) -> None:
    response = http.post("/v1/component/ram", params={"criteria": "all"}, json={})
    assert response.status_code == 200


@pytest.mark.xfail(strict=True, reason="unknown usage_location is accepted silently")
def test_quirk_unknown_location_is_rejected(http: httpx2.Client) -> None:
    response = http.post("/v1/component/cpu", json={"usage": {"usage_location": "XXX"}})
    assert 400 <= response.status_code < 500


@pytest.mark.xfail(strict=True, reason="unknown cloud region is accepted silently")
def test_quirk_unknown_region_is_rejected(http: httpx2.Client) -> None:
    response = http.post(
        "/v1/cloud/instance",
        json={
            "provider": "aws",
            "instance_type": "m5.xlarge",
            "usage": {"region": "mars-1"},
        },
    )
    assert 400 <= response.status_code < 500


@pytest.mark.xfail(strict=True, reason="name_to_gpu returns 200 with a plain string")
def test_quirk_unknown_gpu_name_is_404(http: httpx2.Client) -> None:
    response = http.get("/v1/utils/name_to_gpu", params={"gpu_name": "zzzz-nothing"})
    assert response.status_code == 404


@pytest.mark.xfail(strict=True, reason="default IoT archetype reports 0 kgCO2eq")
def test_quirk_default_iot_device_is_not_zero(http: httpx2.Client) -> None:
    response = http.post("/v1/iot/iot_device", params={"criteria": "gwp"}, json={})
    embedded = response.json()["impacts"]["gwp"]["embedded"]
    assert embedded["value"] != 0


@pytest.mark.xfail(
    strict=False,
    reason="GPU + adpe returns 500 until Boavizta/boaviztapi#621 is deployed",
)
def test_quirk_gpu_missing_criteria_return_not_implemented(
    http: httpx2.Client,
) -> None:
    response = http.post("/v1/component/gpu", params={"criteria": "adpe"}, json={})
    assert response.status_code == 200
