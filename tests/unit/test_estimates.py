import json
from typing import Any

import httpx2
import pytest

from boaviztapi_mcp.catalog import Catalog
from boaviztapi_mcp.client import BoaviztaClient
from boaviztapi_mcp.config import Settings
from boaviztapi_mcp.errors import InputError, UpstreamServerError
from boaviztapi_mcp.estimates import CompareItem, Estimator
from boaviztapi_mcp.models import (
    CloudInstanceRequest,
    ComponentRequest,
    DeviceRequest,
    ServerRequest,
)
from tests import scenarios
from tests.replay import ReplayTransport

pytestmark = pytest.mark.anyio


def posts(replay: ReplayTransport) -> list[dict[str, Any]]:
    return [key for key in replay.seen if key["method"] == "POST"]


def params(key: dict[str, Any], name: str) -> list[str]:
    return [value for param, value in key["params"] if param == name]


async def test_acceptance_1_gpu_in_germany(
    client: BoaviztaClient, replay: ReplayTransport
) -> None:
    result = await scenarios.h100_germany_year(client)

    (request,) = posts(replay)
    assert request["path"] == "/v1/component/gpu"
    assert request["body"] == {
        "units": 4,
        "name": "NVIDIA H100 SXM 80GB",
        "usage": {"usage_location": "DEU"},
    }
    assert params(request, "duration") == ["8760"]
    assert sorted(params(request, "criteria")) == ["adp", "gwp", "pe"]
    assert params(request, "verbose") == ["true"]

    assert result.subject.name == "4x NVIDIA H100 SXM 80GB"
    assert result.subject.requested_as == "h100 sxm"
    assert result.duration.basis == "requested"
    assert result.duration.lifetime_hours == 26280
    assert result.location.code == "DEU"
    assert result.location.basis == "requested"
    gwp = result.impacts[0]
    assert (gwp.criterion, gwp.embedded.value, gwp.use.value) == ("gwp", 766.8, 7100)
    assert result.api.version == "2.6.0"


async def test_acceptance_2_compare_locations(client: BoaviztaClient) -> None:
    result = await scenarios.m5_france_vs_us_month(client)
    gwp = result.comparison[0]
    assert gwp.criterion == "gwp"
    assert [row.label for row in gwp.rows] == ["France", "United States"]
    assert gwp.lowest == "France"
    assert gwp.rows[1].delta_vs_first_pct is not None
    assert gwp.rows[1].delta_vs_first_pct > 100
    assert gwp.ranges_overlap is True


async def test_acceptance_3_laptop_defaults(client: BoaviztaClient) -> None:
    result = await scenarios.laptop_full_life(client)
    assert result.duration.basis == "full_lifetime"
    assert result.duration.hours == 35040
    assert result.location.basis == "default_mix"
    assert result.location.code == "EEE"
    assert result.impacts[0].embedded.value == 181
    assert result.impacts[1].embedded.status == "not_implemented"
    assert result.impacts[1].total is None
    assert any("No location given" in note for note in result.notes)


async def test_acceptance_4_region_and_load(
    client: BoaviztaClient, replay: ReplayTransport
) -> None:
    result = await scenarios.two_instances_same_region(client)
    first = posts(replay)[0]
    assert first["body"]["usage"] == {"region": "eu-west-3", "time_workload": 50}
    assert result.results[0].location.basis == "region"
    assert result.results[0].location.region == "eu-west-3"
    assert result.comparison[0].lowest == "m5.xlarge"
    assert result.comparison[0].ranges_overlap is False


async def test_acceptance_5_server_beyond_lifetime(
    client: BoaviztaClient, replay: ReplayTransport
) -> None:
    result = await scenarios.xeon_server_five_years(client)
    (request,) = posts(replay)
    assert request["path"] == "/v1/server/"
    assert request["body"]["configuration"] == {
        "cpu": {"name": "Intel Xeon Gold 6134", "units": 2},
        "ram": [{"units": 12, "capacity": 32}],
    }
    assert params(request, "archetype") == []
    assert result.duration.exceeds_lifetime is True
    assert any("longer than the hardware lifetime" in n for n in result.notes)
    assert any("archetype platform_compute_medium: SSD" in n for n in result.notes)
    assert result.breakdown is not None
    assert {c.component.split("-")[0] for c in result.breakdown} >= {"CPU", "RAM"}


async def test_failing_criterion_falls_back_per_criterion(
    client: BoaviztaClient, replay: ReplayTransport
) -> None:
    result = await scenarios.gpu_with_failing_criterion(client)
    sent = [sorted(params(key, "criteria")) for key in posts(replay)]
    assert sent == [["adpe", "gwp"], ["gwp"], ["adpe"]]
    gwp, adpe = result.impacts
    assert gwp.embedded.status == "ok"
    assert adpe.embedded.status == "upstream_error"
    assert adpe.unit == "kg SB eq."
    assert any("failed (HTTP 500) for: adpe" in note for note in result.notes)


async def test_negative_values_pass_through(client: BoaviztaClient) -> None:
    result = await scenarios.laptop_water_use(client)
    wu = result.impacts[0]
    assert wu.embedded.value == -812
    assert wu.embedded.warnings == ["Generic data used for impact calculation."]


async def test_iot_device_breakdown(client: BoaviztaClient) -> None:
    result = await scenarios.smart_watch(client)
    assert result.subject.name == "iot device (smart_watch)"
    assert result.breakdown is not None
    assert len(result.breakdown) > 3
    assert not any("No location given" in note for note in result.notes)


async def test_gpu_server_notes_archetype_parts(
    client: BoaviztaClient, replay: ReplayTransport
) -> None:
    result = await scenarios.gpu_server(client)
    (request,) = posts(replay)
    assert params(request, "archetype") == ["platfom_gpucompute_high"]
    assert request["body"]["usage"] == {
        "gpu_time_workload": 80,
        "usage_location": "DEU",
    }
    assert any("CPU, RAM, SSD" in note for note in result.notes)


@pytest.fixture
def estimator(client: BoaviztaClient, catalog: Catalog) -> Estimator:
    return Estimator(client, catalog)


@pytest.mark.parametrize(
    ("request_", "message"),
    [
        (DeviceRequest(device_type="iot_device"), "needs an archetype"),
        (
            CloudInstanceRequest(
                provider="aws",
                instance_type="m5.xlarge",
                region="eu-west-3",
                usage_location="FRA",
            ),
            "either region or usage_location",
        ),
        (
            CloudInstanceRequest(
                provider="aws", instance_type="m5.xlarge", region="mars-1"
            ),
            "Unknown aws region",
        ),
        (
            CloudInstanceRequest(
                provider="aws", instance_type="m5.xlarge", usage_location="XXX"
            ),
            "Unknown location",
        ),
        (ComponentRequest(component="ram", name="x"), "name applies to gpu and cpu"),
        (ComponentRequest(component="gpu", capacity_gb=8), "capacity_gb applies"),
        (ComponentRequest(component="ssd", tdp_w=8), "tdp_w applies"),
        (ComponentRequest(component="gpu", name="h100"), "matches 3 names"),
        (ServerRequest(archetype="platform_nope"), "Unknown server archetype"),
    ],
)
async def test_input_errors(estimator: Estimator, request_: Any, message: str) -> None:
    with pytest.raises(InputError, match=message):
        await estimator.run(request_)


async def test_rejects_bad_duration_and_criteria(estimator: Estimator) -> None:
    gpu = ComponentRequest(component="gpu")
    with pytest.raises(InputError, match="greater than 0"):
        await estimator.run(gpu, duration_hours=0)
    with pytest.raises(InputError, match="'all' is not supported"):
        await estimator.run(gpu, criteria=["all"])


async def test_compare_validation(estimator: Estimator) -> None:
    item = CompareItem("a", ComponentRequest(component="gpu"))
    with pytest.raises(InputError, match="2 to 5 items"):
        await estimator.compare([item], duration_hours=1)
    with pytest.raises(InputError, match="different label"):
        await estimator.compare([item, item], duration_hours=1)
    bad = CompareItem("b", DeviceRequest(device_type="iot_device"))
    with pytest.raises(InputError, match="Item 'b': iot_device needs"):
        await estimator.compare([item, bad], duration_hours=1)


async def test_single_criterion_500_is_raised(replay: ReplayTransport) -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            return httpx2.Response(500, text="Internal Server Error")
        return await replay.handle_async_request(request)

    client = BoaviztaClient(Settings(), transport=httpx2.MockTransport(handler))
    estimator = Estimator(client, Catalog(client))
    with pytest.raises(UpstreamServerError):
        await estimator.run(ComponentRequest(component="gpu"), criteria=["gwp"])
    with pytest.raises(UpstreamServerError, match="every requested criterion"):
        await estimator.run(ComponentRequest(component="gpu"), criteria=["gwp", "pe"])


async def test_criteria_default_from_settings(replay: ReplayTransport) -> None:
    sent: list[list[str]] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            sent.append(request.url.params.get_list("criteria"))
            body = {
                "impacts": {
                    "pe": {
                        "unit": "MJ",
                        "description": "",
                        "embedded": {"value": 1.0},
                        "use": {"value": 2.0},
                    }
                }
            }
            return httpx2.Response(200, content=json.dumps(body))
        return await replay.handle_async_request(request)

    client = BoaviztaClient(Settings(), transport=httpx2.MockTransport(handler))
    estimator = Estimator(client, Catalog(client), default_criteria=("pe",))
    result = await estimator.run(ComponentRequest(component="ssd", capacity_gb=512))
    assert sent == [["pe"]]
    assert result.subject.name == "1x 512 GB SSD"
    assert result.impacts[0].total is not None


async def test_empty_cpu_block_does_not_count_as_given(estimator: Estimator) -> None:
    from boaviztapi_mcp.models import CpuSpec

    prepared = await estimator.prepare(ServerRequest(cpu=CpuSpec()))
    assert prepared.server_parts_given == set()
    assert "configuration" not in prepared.body


async def test_interpreted_names_are_noted(estimator: Estimator) -> None:
    prepared = await estimator.prepare(
        ComponentRequest(component="gpu", name="h100 sxm")
    )
    assert prepared.notes[0] == "GPU 'h100 sxm' was read as NVIDIA H100 SXM 80GB."
    exact = await estimator.prepare(
        ComponentRequest(component="gpu", name="nvidia h100 sxm 80gb")
    )
    assert not any("was read as" in note for note in exact.notes)
