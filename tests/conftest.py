from collections.abc import AsyncIterator

import pytest

from boaviztapi_mcp.catalog import Catalog
from boaviztapi_mcp.client import BoaviztaClient
from boaviztapi_mcp.config import Settings
from tests.replay import ReplayTransport


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def replay() -> ReplayTransport:
    return ReplayTransport()


@pytest.fixture
async def client(replay: ReplayTransport) -> AsyncIterator[BoaviztaClient]:
    client = BoaviztaClient(Settings(), transport=replay, retry_delay=0)
    yield client
    await client.aclose()


@pytest.fixture
def catalog(client: BoaviztaClient) -> Catalog:
    return Catalog(client)
