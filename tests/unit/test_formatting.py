import os
from pathlib import Path

import pytest

from boaviztapi_mcp.client import BoaviztaClient
from boaviztapi_mcp.formatting import human_hours, number, phase_text
from boaviztapi_mcp.models import Phase
from tests import scenarios

pytestmark = pytest.mark.anyio

GOLDEN = Path(__file__).parent.parent / "golden"
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (7100.0, "7100"),
        (766.8, "766.8"),
        (479.49999999999994, "479.5"),
        (0.0002155, "0.0002155"),
        (1.94e-07, "1.94e-07"),
        (-812.0, "-812"),
    ],
)
def test_number(value: float, text: str) -> None:
    assert number(value) == text


@pytest.mark.parametrize(
    ("hours", "text"),
    [
        (8760, "1 year"),
        (730, "1 month"),
        (43800, "5 years"),
        (26280, "3 years"),
        (1460, "2 months"),
        (100, "4.17 days"),
        (24, "24 h"),
        (10000, "1.14 years"),
    ],
)
def test_human_hours(hours: float, text: str) -> None:
    assert human_hours(hours) == text


def test_phase_text() -> None:
    assert phase_text(Phase(status="not_implemented")) == (
        "not available from BoaviztAPI for this item"
    )
    assert "failed" in phase_text(Phase(status="upstream_error"))
    assert phase_text(Phase(status="ok", value=5, min=5, max=5)) == "5"
    assert phase_text(
        Phase(status="ok", value=5, min=1, max=9, warnings=["Generic data."])
    ) == ("5 (range 1 to 9) [warning: Generic data]")


SUMMARY_SCENARIOS = [n for n in scenarios.SCENARIOS if not n.startswith("catalog_")]


@pytest.mark.parametrize("name", SUMMARY_SCENARIOS)
async def test_golden_summaries(client: BoaviztaClient, name: str) -> None:
    result = await scenarios.SCENARIOS[name](client)
    path = GOLDEN / f"{name}.txt"
    if UPDATE:
        path.parent.mkdir(exist_ok=True)
        path.write_text(result.summary + "\n")
    assert result.summary + "\n" == path.read_text()
