"""Calls whose upstream responses are recorded as fixtures.

Each scenario drives the real code with a client; scripts/record_fixtures.py
runs them against a live BoaviztAPI and the tests replay the result. Tests call
the same functions, so a scenario and its fixtures can never drift apart.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from boaviztapi_mcp.catalog import DEVICE_FAMILIES, Catalog
from boaviztapi_mcp.client import BoaviztaClient
from boaviztapi_mcp.estimates import CompareItem, Estimator
from boaviztapi_mcp.models import (
    CloudInstanceRequest,
    ComparisonResult,
    ComponentRequest,
    CpuSpec,
    DeviceRequest,
    EstimateResult,
    GpuSpec,
    RamSpec,
    ServerRequest,
)

Scenario = Callable[[BoaviztaClient], Awaitable[Any]]


def estimator(client: BoaviztaClient) -> Estimator:
    return Estimator(client, Catalog(client))


async def catalog_lists(client: BoaviztaClient) -> None:
    catalog = Catalog(client)
    await catalog.gpu_names()
    await catalog.cpu_names()
    await catalog.providers()
    await catalog.instances("aws")
    await catalog.instances("scaleway")
    await catalog.regions()
    await catalog.server_archetypes()
    for device_type in DEVICE_FAMILIES:
        await catalog.device_archetypes(device_type)
    await catalog.countries()
    await catalog.criteria()


async def h100_germany_year(client: BoaviztaClient) -> EstimateResult:
    """Acceptance 1: footprint of 4 H100 SXM for a year in Germany."""
    return await estimator(client).run(
        ComponentRequest(
            component="gpu", name="h100 sxm", units=4, usage_location="Germany"
        ),
        duration_hours=8760,
    )


async def m5_france_vs_us_month(client: BoaviztaClient) -> ComparisonResult:
    """Acceptance 2: aws m5.xlarge in France vs the US for a month."""
    return await estimator(client).compare(
        [
            CompareItem(
                "France",
                CloudInstanceRequest(
                    provider="aws", instance_type="m5.xlarge", usage_location="FRA"
                ),
            ),
            CompareItem(
                "United States",
                CloudInstanceRequest(
                    provider="aws", instance_type="m5.xlarge", usage_location="USA"
                ),
            ),
        ],
        duration_hours=730,
    )


async def laptop_full_life(client: BoaviztaClient) -> EstimateResult:
    """Acceptance 3: embedded carbon of a typical laptop."""
    return await estimator(client).run(DeviceRequest(device_type="laptop"))


async def two_instances_same_region(client: BoaviztaClient) -> ComparisonResult:
    """Acceptance 4: which of two cloud instances is greener."""
    return await estimator(client).compare(
        [
            CompareItem(
                "m5.xlarge",
                CloudInstanceRequest(
                    provider="aws",
                    instance_type="m5.xlarge",
                    region="eu-west-3",
                    load_percent=50,
                ),
            ),
            CompareItem(
                "c5.2xlarge",
                CloudInstanceRequest(
                    provider="aws",
                    instance_type="c5.2xlarge",
                    region="eu-west-3",
                    load_percent=50,
                ),
            ),
        ],
        duration_hours=8760,
    )


async def xeon_server_five_years(client: BoaviztaClient) -> EstimateResult:
    """Acceptance 5: 2x Xeon Gold 6134, 384 GB RAM, 5 years in France."""
    return await estimator(client).run(
        ServerRequest(
            cpu=CpuSpec(name="xeon gold 6134", units=2),
            ram=[RamSpec(units=12, capacity_gb=32)],
            usage_location="France",
        ),
        duration_hours=43800,
        detail="breakdown",
    )


async def gpu_with_failing_criterion(client: BoaviztaClient) -> EstimateResult:
    """A criterion that makes the GPU endpoint fail triggers the fallback."""
    return await estimator(client).run(
        ComponentRequest(component="gpu", name="NVIDIA H100 SXM 80GB"),
        criteria=["gwp", "adpe"],
    )


async def laptop_water_use(client: BoaviztaClient) -> EstimateResult:
    """Negative values and a use phase that is not implemented."""
    return await estimator(client).run(
        DeviceRequest(device_type="laptop", usage_location="FRA"),
        criteria=["wu", "gwp"],
    )


async def smart_watch(client: BoaviztaClient) -> EstimateResult:
    return await estimator(client).run(
        DeviceRequest(device_type="iot_device", archetype="smart_watch"),
        detail="breakdown",
    )


async def ram_module(client: BoaviztaClient) -> EstimateResult:
    return await estimator(client).run(
        ComponentRequest(component="ram", capacity_gb=64, usage_location="FRA"),
        duration_hours=8760,
    )


async def gpu_server(client: BoaviztaClient) -> EstimateResult:
    return await estimator(client).run(
        ServerRequest(
            archetype="platfom_gpucompute_high",
            gpu=GpuSpec(name="NVIDIA A100 SXM4 80GB", units=8),
            gpu_load_percent=80,
            usage_location="DEU",
        ),
        duration_hours=8760,
    )


SCENARIOS: dict[str, Scenario] = {
    "catalog_lists": catalog_lists,
    "h100_germany_year": h100_germany_year,
    "m5_france_vs_us_month": m5_france_vs_us_month,
    "laptop_full_life": laptop_full_life,
    "two_instances_same_region": two_instances_same_region,
    "xeon_server_five_years": xeon_server_five_years,
    "gpu_with_failing_criterion": gpu_with_failing_criterion,
    "laptop_water_use": laptop_water_use,
    "smart_watch": smart_watch,
    "ram_module": ram_module,
    "gpu_server": gpu_server,
}
