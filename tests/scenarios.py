"""Calls whose upstream responses are recorded as fixtures.

Each scenario drives the real code with a client; scripts/record_fixtures.py
runs them against a live BoaviztAPI and the tests replay the result.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from boaviztapi_mcp.catalog import DEVICE_FAMILIES, Catalog
from boaviztapi_mcp.client import BoaviztaClient

Scenario = Callable[[BoaviztaClient], Awaitable[object]]


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


SCENARIOS: dict[str, Scenario] = {
    "catalog_lists": catalog_lists,
}
