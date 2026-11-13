from boaviztapi_mcp.models import Phase
from boaviztapi_mcp.parsing import (
    assumptions,
    parse_impacts,
    parse_phase,
    parse_verbose,
    round_sig,
    total_of,
)


def test_numeric_phase_keeps_range_and_warnings() -> None:
    phase = parse_phase(
        {"value": 1200.0, "min": 694.8, "max": 2207.0, "warnings": ["End of life."]}
    )
    assert phase == Phase(
        status="ok", value=1200, min=694.8, max=2207, warnings=["End of life."]
    )


def test_not_implemented_phase() -> None:
    assert parse_phase("not implemented").status == "not_implemented"
    assert parse_phase(None).status == "not_implemented"
    assert parse_phase({"value": None}).status == "not_implemented"


def test_total_only_when_both_phases_are_numeric() -> None:
    impacts = parse_impacts(
        {
            "gwp": {
                "unit": "kgCO2eq",
                "description": "Total climate change",
                "embedded": {"value": 766.8, "min": 766.8, "max": 766.8},
                "use": {"value": 7100.0, "min": 1035.0, "max": 10350.0},
            },
            "wu": {
                "unit": "m3 eq.",
                "description": "Use of water resources",
                "embedded": {"value": -812.0, "min": -812.0, "max": -812.0},
                "use": "not implemented",
            },
        }
    )
    gwp, wu = impacts
    assert gwp.total is not None
    assert (gwp.total.value, gwp.total.min, gwp.total.max) == (7867, 1802, 11120)
    assert wu.embedded.value == -812
    assert wu.use.status == "not_implemented"
    assert wu.total is None


def test_total_uses_value_when_bounds_are_missing() -> None:
    total = total_of(Phase(status="ok", value=2), Phase(status="ok", value=3, min=1))
    assert total is not None
    assert (total.value, total.min, total.max) == (5, 3, 5)


def test_round_sig() -> None:
    assert round_sig(7866.8) == 7867
    assert round_sig(0.00092756) == 0.0009276
    assert round_sig(-809.1) == -809.1
    assert round_sig(0) == 0


def test_parse_verbose_flat_attributes_and_components() -> None:
    info = parse_verbose(
        {
            "duration": {"value": 8760.0, "unit": "hours"},
            "CPU-1": {
                "impacts": {"gwp": {"unit": "kgCO2eq", "embedded": {"value": 10.0}}},
                "units": {"value": 2, "status": "INPUT"},
            },
            "avg_power": {
                "value": 479.49999999999994,
                "status": "COMPLETED",
                "unit": "W",
            },
            "usage_location": {"value": "DEU", "status": "INPUT", "unit": "CodSP3"},
            "hours_life_time": {
                "value": 26280.0,
                "status": "ARCHETYPE",
                "unit": "hours",
            },
            "params": {"value": {"a": 1}, "status": "ARCHETYPE"},
            "impacts": {"gwp": {}},
        }
    )
    assert info.duration_hours == 8760
    assert info.lifetime_hours == 26280
    assert info.location_code == "DEU"
    assert [c.component for c in info.components] == ["CPU-1"]
    assert info.components[0].impacts[0].embedded.value == 10
    assert set(info.attributes) == {"avg_power", "usage_location", "hours_life_time"}

    key = assumptions(info, everything=False)
    assert [(a.name, a.value, a.unit) for a in key] == [
        ("average power", 479.5, "W"),
        ("electricity location", "DEU", None),
        ("lifetime", 26280, "hours"),
    ]


def test_parse_verbose_tolerates_missing_or_odd_input() -> None:
    assert parse_verbose(None).components == []
    assert parse_verbose({"duration": "soon", "x": 1}).duration_hours is None


def test_merge_verbose_combines_component_impacts() -> None:
    from boaviztapi_mcp.parsing import merge_verbose

    first = {
        "avg_power": {"value": 1.0},
        "CPU-1": {"impacts": {"gwp": {"embedded": {"value": 1.0}}}},
    }
    second = {
        "avg_power": {"value": 2.0},
        "CPU-1": {"impacts": {"pe": {"embedded": {"value": 3.0}}}},
        "RAM-1": {"impacts": {"pe": {"embedded": {"value": 4.0}}}},
    }
    merged = merge_verbose([first, second, None])
    assert merged["avg_power"] == {"value": 1.0}
    assert set(merged["CPU-1"]["impacts"]) == {"gwp", "pe"}
    assert set(merged["RAM-1"]["impacts"]) == {"pe"}
    assert first["CPU-1"]["impacts"] == {"gwp": {"embedded": {"value": 1.0}}}
    assert merge_verbose([None]) is None


def test_assumptions_keep_ranges() -> None:
    info = parse_verbose(
        {"avg_power": {"value": 479.5, "unit": "W", "min": 70.0, "max": 700.0}}
    )
    (power,) = assumptions(info, everything=False)
    assert (power.min, power.max) == (70, 700)
