"""Pydantic models for tool inputs and structured tool output."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from boaviztapi_mcp.catalog import DeviceType

PhaseStatus = Literal["ok", "not_implemented", "upstream_error"]
ComponentKind = Literal["gpu", "cpu", "ram", "ssd", "hdd"]
Detail = Literal["summary", "breakdown"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Inputs ----------------------------------------------------------------------


class CloudInstanceRequest(_Model):
    provider: str = Field(description="Cloud provider, e.g. 'aws', 'gcp', 'azure'.")
    instance_type: str = Field(description="Exact instance type, e.g. 'm5.xlarge'.")
    region: str | None = Field(
        default=None,
        description="Provider region, e.g. 'eu-west-3'. Exclusive with usage_location.",
    )
    usage_location: str | None = Field(
        default=None,
        description="Country name or 3-letter code where it runs, e.g. 'FRA'.",
    )
    load_percent: float | None = Field(
        default=None, ge=0, le=100, description="Average CPU load in percent."
    )


class CpuSpec(_Model):
    name: str | None = Field(default=None, description="CPU model name.")
    units: int | None = Field(default=None, ge=1, description="Number of CPUs.")
    core_units: int | None = Field(default=None, ge=1, description="Cores per CPU.")
    tdp_w: float | None = Field(default=None, gt=0, description="TDP in watts.")


class RamSpec(_Model):
    units: int = Field(default=1, ge=1, description="Number of modules.")
    capacity_gb: int = Field(gt=0, description="Capacity of one module in GB.")


class DiskSpec(_Model):
    type: Literal["ssd", "hdd"]
    units: int = Field(default=1, ge=1, description="Number of disks.")
    capacity_gb: int | None = Field(
        default=None, gt=0, description="Capacity of one disk in GB."
    )


class GpuSpec(_Model):
    name: str | None = Field(default=None, description="GPU model name.")
    units: int = Field(default=1, ge=1, description="Number of GPUs.")


class ServerRequest(_Model):
    archetype: str | None = Field(
        default=None,
        description="Server archetype used for anything not given; default"
        " 'platform_compute_medium'.",
    )
    server_type: Literal["rack", "blade"] | None = None
    cpu: CpuSpec | None = None
    ram: list[RamSpec] | None = None
    disks: list[DiskSpec] | None = None
    gpu: GpuSpec | None = None
    avg_power_w: float | None = Field(default=None, gt=0)
    load_percent: float | None = Field(default=None, ge=0, le=100)
    gpu_load_percent: float | None = Field(default=None, ge=0, le=100)
    use_time_ratio: float | None = Field(default=None, ge=0, le=1)
    lifetime_hours: float | None = Field(default=None, gt=0)
    usage_location: str | None = None


class ComponentRequest(_Model):
    component: ComponentKind
    name: str | None = Field(default=None, description="Model name (gpu, cpu only).")
    units: int = Field(default=1, ge=1)
    capacity_gb: int | None = Field(default=None, gt=0, description="ram, ssd, hdd.")
    tdp_w: float | None = Field(default=None, gt=0, description="gpu, cpu only.")
    avg_power_w: float | None = Field(default=None, gt=0)
    load_percent: float | None = Field(default=None, ge=0, le=100)
    lifetime_hours: float | None = Field(default=None, gt=0)
    usage_location: str | None = None


class DeviceRequest(_Model):
    device_type: DeviceType
    archetype: str | None = None
    avg_power_w: float | None = Field(default=None, gt=0)
    use_time_ratio: float | None = Field(default=None, ge=0, le=1)
    lifetime_hours: float | None = Field(default=None, gt=0)
    usage_location: str | None = None


# Output ----------------------------------------------------------------------


class Phase(BaseModel):
    status: PhaseStatus
    value: float | None = None
    min: float | None = None
    max: float | None = None
    warnings: list[str] = Field(default_factory=list)


class Total(BaseModel):
    value: float
    min: float
    max: float


class Impact(BaseModel):
    criterion: str
    unit: str
    description: str
    embedded: Phase
    use: Phase
    total: Total | None = Field(
        default=None, description="embedded + use; only when both phases are 'ok'."
    )


class ComponentImpacts(BaseModel):
    component: str
    impacts: list[Impact]


class Subject(BaseModel):
    kind: str
    name: str
    units: int | None = None
    provider: str | None = None
    requested_as: str | None = Field(
        default=None, description="What the caller typed, when it was resolved."
    )


class Duration(BaseModel):
    hours: float | None
    basis: Literal["requested", "full_lifetime"]
    lifetime_hours: float | None = None
    exceeds_lifetime: bool = False


class Location(BaseModel):
    code: str | None = None
    name: str | None = None
    basis: Literal["requested", "region", "default_mix"]
    region: str | None = None


class Assumption(BaseModel):
    name: str
    value: Any
    unit: str | None = None
    status: str | None = None
    source: str | None = None


class ApiInfo(BaseModel):
    base_url: str
    version: str


class EstimateResult(BaseModel):
    summary: str = Field(description="Plain-text digest; quote it or use the fields.")
    subject: Subject
    duration: Duration
    location: Location
    impacts: list[Impact]
    assumptions: list[Assumption]
    breakdown: list[ComponentImpacts] | None = None
    notes: list[str] = Field(default_factory=list)
    api: ApiInfo


class ComparisonRow(BaseModel):
    label: str
    embedded: float | None
    use: float | None
    total: float | None
    total_min: float | None
    total_max: float | None
    delta_vs_first_pct: float | None


class CriterionComparison(BaseModel):
    criterion: str
    unit: str
    rows: list[ComparisonRow]
    lowest: str | None = Field(description="Label with the lowest total, if rankable.")
    ranges_overlap: bool | None = Field(
        description="True when the lowest item's range overlaps another item's range."
    )


class ComparisonResult(BaseModel):
    summary: str
    comparison: list[CriterionComparison]
    results: list[EstimateResult]


class SearchResult(BaseModel):
    summary: str
    kind: str
    query: str | None
    total_matches: int
    names: list[str]


class CatalogItem(BaseModel):
    summary: str
    kind: str
    name: str
    details: dict[str, Any]


class CriterionInfo(BaseModel):
    code: str
    unit: str
    description: str
    method: str | None


class CriteriaList(BaseModel):
    summary: str
    criteria: list[CriterionInfo]
