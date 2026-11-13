"""Turn BoaviztAPI JSON into result models. No arithmetic beyond the total."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, TypeGuard

from boaviztapi_mcp.models import Assumption, ComponentImpacts, Impact, Phase, Total

NOT_IMPLEMENTED = "not implemented"
COMPONENT_KEY = re.compile(r"^[A-Z][A-Z_]*-\d+$")

# Verbose attributes worth showing in the summary, with readable names.
KEY_ASSUMPTIONS: dict[str, str] = {
    "units": "units",
    "hours_life_time": "lifetime",
    "avg_power": "average power",
    "time_workload": "load",
    "use_time_ratio": "use time ratio",
    "usage_location": "electricity location",
    "gwp_factor": "grid carbon intensity",
    "tdp": "TDP",
    "vcpu": "vCPUs",
    "memory": "memory",
    "capacity": "capacity",
    "type": "type",
}
SKIPPED_ATTRIBUTES = frozenset({"impacts", "duration", "params"})


def parse_phase(raw: Any) -> Phase:
    if isinstance(raw, Mapping) and _is_number(raw.get("value")):
        warnings = raw.get("warnings") or []
        return Phase(
            status="ok",
            value=float(raw["value"]),
            min=float(raw["min"]) if _is_number(raw.get("min")) else None,
            max=float(raw["max"]) if _is_number(raw.get("max")) else None,
            warnings=[str(w) for w in warnings],
        )
    return Phase(status="not_implemented")


def parse_impacts(raw: Mapping[str, Any]) -> list[Impact]:
    impacts = []
    for criterion, data in raw.items():
        data = data if isinstance(data, Mapping) else {}
        embedded = parse_phase(data.get("embedded"))
        use = parse_phase(data.get("use"))
        impacts.append(
            Impact(
                criterion=str(criterion),
                unit=str(data.get("unit") or ""),
                description=str(data.get("description") or ""),
                embedded=embedded,
                use=use,
                total=total_of(embedded, use),
            )
        )
    return impacts


def total_of(embedded: Phase, use: Phase) -> Total | None:
    """Sum the two phases, rounded to 4 significant figures like the API."""
    if embedded.status != "ok" or use.status != "ok":
        return None
    assert embedded.value is not None
    assert use.value is not None
    value = embedded.value + use.value
    low = _or(embedded.min, embedded.value) + _or(use.min, use.value)
    high = _or(embedded.max, embedded.value) + _or(use.max, use.value)
    return Total(value=round_sig(value), min=round_sig(low), max=round_sig(high))


def round_sig(value: float, digits: int = 4) -> float:
    if value == 0 or not math.isfinite(value):
        return value
    return round(value, digits - 1 - math.floor(math.log10(abs(value))))


@dataclass
class VerboseInfo:
    duration_hours: float | None = None
    lifetime_hours: float | None = None
    location_code: str | None = None
    location_status: str | None = None
    attributes: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    components: list[ComponentImpacts] = field(default_factory=list)


def parse_verbose(raw: Any) -> VerboseInfo:
    info = VerboseInfo()
    if not isinstance(raw, Mapping):
        return info
    for key, value in raw.items():
        if not isinstance(value, Mapping):
            continue
        if COMPONENT_KEY.match(key) and isinstance(value.get("impacts"), Mapping):
            info.components.append(
                ComponentImpacts(component=key, impacts=parse_impacts(value["impacts"]))
            )
            continue
        if key == "duration" and _is_number(value.get("value")):
            info.duration_hours = float(value["value"])
            continue
        if key in SKIPPED_ATTRIBUTES or "value" not in value:
            continue
        info.attributes[key] = value
    lifetime = info.attributes.get("hours_life_time", {}).get("value")
    if _is_number(lifetime):
        info.lifetime_hours = float(lifetime)
    location = info.attributes.get("usage_location", {})
    if isinstance(location.get("value"), str):
        info.location_code = location["value"]
        info.location_status = location.get("status")
    return info


def assumptions(info: VerboseInfo, *, everything: bool) -> list[Assumption]:
    """Readable assumptions; only the key ones unless ``everything``."""
    result = []
    for key, attribute in info.attributes.items():
        label = KEY_ASSUMPTIONS.get(key)
        if label is None:
            if not everything:
                continue
            label = key.replace("_", " ")
        value = attribute.get("value")
        if isinstance(value, Mapping) and not everything:
            continue
        unit = attribute.get("unit")
        if key == "usage_location":
            unit = None
        result.append(
            Assumption(
                name=label,
                value=_tidy(value),
                unit=str(unit) if unit else None,
                status=str(attribute["status"]) if attribute.get("status") else None,
                source=str(attribute["source"]) if attribute.get("source") else None,
            )
        )
    return result


def _tidy(value: Any) -> Any:
    if isinstance(value, float):
        return round_sig(value, 6)
    return value


def _or(value: float | None, default: float) -> float:
    return default if value is None else value


def _is_number(value: Any) -> TypeGuard[float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
