"""Plain-text summaries. Every number keeps its unit and its range."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from boaviztapi_mcp.models import (
        ComparisonResult,
        EstimateResult,
        Impact,
        Phase,
    )

NOT_AVAILABLE = "not available from BoaviztAPI for this item"
UPSTREAM_FAILED = "BoaviztAPI failed for this criterion (HTTP 500)"
HOURS_PER_YEAR = 8760
HOURS_PER_MONTH = 730
SUMMARY_ASSUMPTIONS = 8
SUMMARY_ASSUMPTION_NAMES = frozenset(
    {
        "units",
        "lifetime",
        "average power",
        "load",
        "use time ratio",
        "grid carbon intensity",
        "TDP",
        "vCPUs",
        "memory",
        "capacity",
        "type",
    }
)


def number(value: float) -> str:
    """Render a number without float noise and without extra rounding."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return format(value, ".10g")


def human_hours(hours: float) -> str:
    if hours == HOURS_PER_YEAR:
        return "1 year"
    if hours == HOURS_PER_MONTH:
        return "1 month"
    if hours >= HOURS_PER_YEAR and hours % HOURS_PER_YEAR == 0:
        return f"{number(hours / HOURS_PER_YEAR)} years"
    if hours >= HOURS_PER_YEAR:
        return f"{hours / HOURS_PER_YEAR:.3g} years"
    if hours >= HOURS_PER_MONTH and hours % HOURS_PER_MONTH == 0:
        return f"{number(hours / HOURS_PER_MONTH)} months"
    if hours >= 48:
        return f"{hours / 24:.3g} days"
    return f"{number(hours)} h"


def value_range(value: float, low: float | None, high: float | None) -> str:
    text = number(value)
    if low is not None and high is not None and (low != value or high != value):
        text += f" (range {number(low)} to {number(high)})"
    return text


def phase_text(phase: Phase) -> str:
    if phase.status == "not_implemented":
        return NOT_AVAILABLE
    if phase.status == "upstream_error":
        return UPSTREAM_FAILED
    assert phase.value is not None
    text = value_range(phase.value, phase.min, phase.max)
    for warning in phase.warnings:
        text += f" [warning: {warning.rstrip('.')}]"
    return text


def headline(result: EstimateResult) -> str:
    duration = result.duration
    if duration.basis == "requested" and duration.hours is not None:
        period = f"over {number(duration.hours)} h ({human_hours(duration.hours)})"
    elif duration.hours is not None:
        period = f"over its full lifetime ({number(duration.hours)} h)"
    else:
        period = "over its full lifetime"
    location = result.location
    code = f" ({location.code})" if location.code else ""
    if location.basis == "region":
        place = f"in {location.region}{code}"
    elif location.basis == "requested":
        place = f"in {location.name or location.code}{code}"
    elif location.code:
        place = f"with the default electricity mix{code}"
    else:
        return f"{result.subject.name}, {period}"
    return f"{result.subject.name}, {period}, {place}"


def allocation_line(result: EstimateResult) -> str | None:
    duration = result.duration
    lifetime = duration.lifetime_hours
    if duration.basis == "full_lifetime":
        return "Embedded = the full manufacturing impact."
    if duration.exceeds_lifetime or lifetime is None or duration.hours is None:
        return None
    return (
        f"Embedded = the share of manufacturing allocated to {number(duration.hours)} h"
        f" of a {number(lifetime)} h lifetime."
    )


def impact_lines(impact: Impact) -> list[str]:
    title = impact.criterion
    if impact.description:
        title += f", {impact.description}"
    unit = f" ({impact.unit})" if impact.unit else ""
    lines = [
        f"{title}{unit}:",
        f"  embedded: {phase_text(impact.embedded)}",
        f"  use: {phase_text(impact.use)}",
    ]
    if impact.total is not None:
        total = impact.total
        lines.append(f"  total: {value_range(total.value, total.min, total.max)}")
    return lines


def format_estimate(result: EstimateResult) -> str:
    lines = [headline(result)]
    allocation = allocation_line(result)
    if allocation:
        lines.append(allocation)
    for impact in result.impacts:
        lines.extend(impact_lines(impact))
    shown = [
        a
        for a in result.assumptions
        if a.name in SUMMARY_ASSUMPTION_NAMES and not isinstance(a.value, (dict, list))
    ][:SUMMARY_ASSUMPTIONS]
    if shown:
        parts = []
        for assumption in shown:
            value = assumption.value
            text = number(value) if isinstance(value, (int, float)) else str(value)
            unit = assumption.unit
            if unit and unit not in ("/1",):
                text += f" {unit}"
            parts.append(f"{assumption.name} {text}")
        lines.append(f"Assumptions: {', '.join(parts)}.")
    lines.extend(f"Note: {note}" for note in result.notes)
    lines.append(f"Source: BoaviztAPI {result.api.version} at {result.api.base_url}")
    return "\n".join(lines)


def format_comparison(
    result: ComparisonResult, labels: Sequence[str], duration_hours: float
) -> str:
    lines = [
        f"Comparison over {number(duration_hours)} h ({human_hours(duration_hours)}):"
    ]
    for label, item in zip(labels, result.results, strict=True):
        lines.append(f"- {label}: {headline(item)}")
    for criterion in result.comparison:
        unit = f" ({criterion.unit})" if criterion.unit else ""
        lines.append(f"{criterion.criterion}{unit}:")
        for row in criterion.rows:
            if row.total is None:
                parts = []
                if row.embedded is not None:
                    parts.append(f"embedded {number(row.embedded)}")
                if row.use is not None:
                    parts.append(f"use {number(row.use)}")
                detail = ", ".join(parts) or NOT_AVAILABLE
                lines.append(f"  {row.label}: no total ({detail})")
                continue
            text = value_range(row.total, row.total_min, row.total_max)
            delta = row.delta_vs_first_pct
            if delta is not None and row is not criterion.rows[0]:
                text += f", {delta:+.1f}% vs {criterion.rows[0].label}"
            lines.append(f"  {row.label}: total {text}")
        if criterion.lowest is None:
            lines.append("  Cannot rank: some items have no total for this criterion.")
        elif criterion.ranges_overlap:
            lines.append(
                f"  Lowest: {criterion.lowest}, but the ranges overlap, so the ranking"
                " is not certain within BoaviztAPI's uncertainty."
            )
        else:
            lines.append(f"  Lowest: {criterion.lowest} (ranges do not overlap).")
    notes = sorted({note for item in result.results for note in item.notes})
    lines.extend(f"Note: {note}" for note in notes)
    if result.results:
        api = result.results[0].api
        lines.append(f"Source: BoaviztAPI {api.version} at {api.base_url}")
    return "\n".join(lines)
