"""Build BoaviztAPI requests, call them, and assemble estimate results."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from boaviztapi_mcp import catalog as cat
from boaviztapi_mcp.client import BoaviztaClient
from boaviztapi_mcp.errors import (
    BoaviztaError,
    InputError,
    UnexpectedResponse,
    UpstreamServerError,
)
from boaviztapi_mcp.formatting import (
    format_comparison,
    format_estimate,
    number,
    query_number,
)
from boaviztapi_mcp.models import (
    ApiInfo,
    CloudInstanceRequest,
    ComparisonResult,
    ComparisonRow,
    ComponentRequest,
    CriterionComparison,
    Detail,
    DeviceRequest,
    Duration,
    EstimateResult,
    Impact,
    Location,
    Phase,
    ServerRequest,
    Subject,
)
from boaviztapi_mcp.parsing import (
    assumptions,
    merge_verbose,
    parse_impacts,
    parse_verbose,
)

DEFAULT_SERVER_ARCHETYPE = "platform_compute_medium"
CONFIGURABLE_SERVER_PARTS = frozenset({"CPU", "RAM", "SSD", "HDD", "GPU"})
MIN_COMPARE_ITEMS = 2
MAX_COMPARE_ITEMS = 5

EstimateRequest = (
    CloudInstanceRequest | ServerRequest | ComponentRequest | DeviceRequest
)


@dataclass
class Prepared:
    """A resolved request, ready to send."""

    kind: str
    name: str
    path: str
    body: dict[str, Any]
    query: list[tuple[str, str]] = field(default_factory=list)
    units: int | None = None
    provider: str | None = None
    requested_as: str | None = None
    location: cat.Location | None = None
    region: str | None = None
    notes: list[str] = field(default_factory=list)
    server_parts_given: set[str] | None = None
    archetype: str | None = None


@dataclass
class CompareItem:
    label: str
    request: EstimateRequest


class Estimator:
    def __init__(
        self,
        client: BoaviztaClient,
        catalog: cat.Catalog,
        default_criteria: Sequence[str] = ("gwp", "adp", "pe"),
    ) -> None:
        self.client = client
        self.catalog = catalog
        self.default_criteria = tuple(default_criteria)

    # Public API ------------------------------------------------------------

    async def run(
        self,
        request: EstimateRequest,
        *,
        duration_hours: float | None = None,
        criteria: Sequence[str] | None = None,
        detail: Detail = "summary",
    ) -> EstimateResult:
        if duration_hours is not None and duration_hours <= 0:
            raise InputError("duration_hours must be greater than 0.")
        prepared = await self.prepare(request)
        return await self._estimate(prepared, duration_hours, criteria, detail)

    async def prepare(self, request: EstimateRequest) -> Prepared:
        if isinstance(request, CloudInstanceRequest):
            return await self._prepare_cloud(request)
        if isinstance(request, ServerRequest):
            return await self._prepare_server(request)
        if isinstance(request, ComponentRequest):
            return await self._prepare_component(request)
        return await self._prepare_device(request)

    async def compare(
        self,
        items: Sequence[CompareItem],
        *,
        duration_hours: float,
        criteria: Sequence[str] | None = None,
    ) -> ComparisonResult:
        if not MIN_COMPARE_ITEMS <= len(items) <= MAX_COMPARE_ITEMS:
            raise InputError(
                f"Compare needs {MIN_COMPARE_ITEMS} to {MAX_COMPARE_ITEMS} items,"
                f" got {len(items)}."
            )
        labels = [item.label for item in items]
        if len(set(labels)) != len(labels):
            raise InputError("Every compared item needs a different label.")
        if duration_hours <= 0:
            raise InputError("duration_hours must be greater than 0.")
        checked = await self.catalog.validate_criteria(
            criteria or self.default_criteria
        )

        async def prepare(item: CompareItem) -> Prepared:
            try:
                return await self.prepare(item.request)
            except BoaviztaError as exc:
                raise InputError(f"Item {item.label!r}: {exc}") from exc

        async def estimate(item: CompareItem, prepared: Prepared) -> EstimateResult:
            try:
                return await self._estimate(
                    prepared, duration_hours, checked, "summary"
                )
            except BoaviztaError as exc:
                raise BoaviztaError(f"Item {item.label!r}: {exc}") from exc

        # Check every item before spending any estimate calls.
        prepared = [await prepare(item) for item in items]
        results = list(
            await asyncio.gather(
                *(estimate(i, p) for i, p in zip(items, prepared, strict=True))
            )
        )
        comparison = [
            _compare_criterion(criterion, labels, results) for criterion in checked
        ]
        result = ComparisonResult(summary="", comparison=comparison, results=results)
        result.summary = format_comparison(result, labels, duration_hours)
        return result

    # Preparation -----------------------------------------------------------

    async def _prepare_cloud(self, req: CloudInstanceRequest) -> Prepared:
        provider = await self.catalog.resolve_provider(req.provider)
        instance = await self.catalog.resolve_instance(provider, req.instance_type)
        if req.region and req.usage_location:
            raise InputError(
                "Give either region or usage_location, not both: the region already"
                " decides the electricity mix."
            )
        usage: dict[str, Any] = {}
        prepared = Prepared(
            kind="cloud_instance",
            name=f"{provider} {instance}",
            path="/v1/cloud/instance",
            body={"provider": provider, "instance_type": instance},
            provider=provider,
            requested_as=None if instance == req.instance_type else req.instance_type,
        )
        prepared.notes.extend(_read_as("Instance type", req.instance_type, instance))
        if req.region:
            prepared.region = await self.catalog.resolve_region(provider, req.region)
            prepared.notes.extend(_read_as("Region", req.region, prepared.region))
            usage["region"] = prepared.region
        elif req.usage_location:
            prepared.location = await self.catalog.resolve_location(req.usage_location)
            usage["usage_location"] = prepared.location.code
        if req.load_percent is not None:
            usage["time_workload"] = req.load_percent
        if usage:
            prepared.body["usage"] = usage
        return prepared

    async def _prepare_server(self, req: ServerRequest) -> Prepared:
        archetype = (
            await self.catalog.resolve_server_archetype(req.archetype)
            if req.archetype
            else None
        )
        config: dict[str, Any] = {}
        given: set[str] = set()
        parts: list[str] = []
        notes: list[str] = []
        if req.archetype and archetype:
            notes.extend(_read_as("Archetype", req.archetype, archetype))
        if req.cpu is not None:
            cpu: dict[str, Any] = {}
            if req.cpu.name:
                cpu["name"] = await self.catalog.resolve_cpu(req.cpu.name)
                notes.extend(_read_as("CPU", req.cpu.name, cpu["name"]))
            if req.cpu.units is not None:
                cpu["units"] = req.cpu.units
            if req.cpu.core_units is not None:
                cpu["core_units"] = req.cpu.core_units
            if req.cpu.tdp_w is not None:
                cpu["tdp"] = round(req.cpu.tdp_w)
            if cpu:
                config["cpu"] = cpu
                given.add("CPU")
                parts.append(f"{cpu.get('units', 1)}x {cpu.get('name', 'CPU')}")
        if req.ram:
            config["ram"] = [
                {"units": ram.units, "capacity": ram.capacity_gb} for ram in req.ram
            ]
            given.add("RAM")
            parts.extend(f"{ram.units}x {ram.capacity_gb} GB RAM" for ram in req.ram)
        if req.disks:
            disks = []
            for disk in req.disks:
                entry: dict[str, Any] = {"type": disk.type, "units": disk.units}
                if disk.capacity_gb is not None:
                    entry["capacity"] = disk.capacity_gb
                disks.append(entry)
                given.add(disk.type.upper())
                size = f"{disk.capacity_gb} GB " if disk.capacity_gb else ""
                parts.append(f"{disk.units}x {size}{disk.type.upper()}")
            config["disk"] = disks
        if req.gpu is not None:
            gpu: dict[str, Any] = {"units": req.gpu.units}
            if req.gpu.name:
                gpu["name"] = await self.catalog.resolve_gpu(req.gpu.name)
                notes.extend(_read_as("GPU", req.gpu.name, gpu["name"]))
            config["gpu"] = gpu
            given.add("GPU")
            parts.append(f"{req.gpu.units}x {gpu.get('name', 'GPU')}")
        body: dict[str, Any] = {}
        if req.server_type:
            body["model"] = {"type": req.server_type}
        if config:
            body["configuration"] = config
        usage, location = await self._usage(
            req.usage_location,
            hours_life_time=req.lifetime_hours,
            avg_power=req.avg_power_w,
            time_workload=req.load_percent,
            gpu_time_workload=req.gpu_load_percent,
            use_time_ratio=req.use_time_ratio,
        )
        if usage:
            body["usage"] = usage
        shown_archetype = archetype or DEFAULT_SERVER_ARCHETYPE
        name = f"server ({', '.join(parts)})" if parts else "server"
        return Prepared(
            kind="server",
            name=f"{name}, archetype {shown_archetype}",
            path="/v1/server/",
            body=body,
            query=[("archetype", archetype)] if archetype else [],
            location=location,
            server_parts_given=given,
            archetype=shown_archetype,
            notes=notes,
        )

    async def _prepare_component(self, req: ComponentRequest) -> Prepared:
        kind = req.component
        if req.name and kind not in ("gpu", "cpu"):
            raise InputError("name applies to gpu and cpu components only.")
        if req.capacity_gb is not None and kind not in ("ram", "ssd", "hdd"):
            raise InputError("capacity_gb applies to ram, ssd and hdd only.")
        if req.tdp_w is not None and kind not in ("gpu", "cpu"):
            raise InputError("tdp_w applies to gpu and cpu only.")
        body: dict[str, Any] = {"units": req.units}
        name = None
        read_as: list[str] = []
        if req.name:
            resolver = (
                self.catalog.resolve_gpu if kind == "gpu" else self.catalog.resolve_cpu
            )
            name = await resolver(req.name)
            body["name"] = name
            read_as = _read_as(kind.upper(), req.name, name)
        if req.capacity_gb is not None:
            body["capacity"] = req.capacity_gb
        if req.tdp_w is not None:
            body["tdp"] = req.tdp_w if kind == "gpu" else round(req.tdp_w)
        usage, location = await self._usage(
            req.usage_location,
            hours_life_time=req.lifetime_hours,
            avg_power=req.avg_power_w,
            time_workload=req.load_percent,
        )
        if usage:
            body["usage"] = usage
        notes = list(read_as)
        if kind == "gpu":
            notes.append(
                "GPU only; the host server is not included. Use estimate_server with"
                " a gpu block for a whole system."
            )
        label = name or (
            f"{req.capacity_gb} GB {kind.upper()}" if req.capacity_gb else kind.upper()
        )
        return Prepared(
            kind=f"component:{kind}",
            name=f"{req.units}x {label}",
            path=f"/v1/component/{kind}",
            body=body,
            units=req.units,
            requested_as=req.name if name and name != req.name else None,
            location=location,
            notes=notes,
        )

    async def _prepare_device(self, req: DeviceRequest) -> Prepared:
        family = cat.device_family(req.device_type)
        if req.device_type == "iot_device" and not req.archetype:
            options = await self.catalog.device_archetypes("iot_device")
            raise InputError(
                "iot_device needs an archetype: without one BoaviztAPI uses a generic"
                " default that reports 0 for manufacturing. Choose one of:"
                f" {', '.join(options)}."
            )
        archetype = (
            await self.catalog.resolve_device_archetype(req.device_type, req.archetype)
            if req.archetype
            else None
        )
        notes = (
            _read_as("Archetype", req.archetype, archetype)
            if req.archetype and archetype
            else []
        )
        usage, location = await self._usage(
            req.usage_location,
            hours_life_time=req.lifetime_hours,
            avg_power=req.avg_power_w,
            use_time_ratio=req.use_time_ratio,
        )
        label = req.device_type.replace("_", " ")
        name = f"{label} ({archetype})" if archetype else f"{label} (default archetype)"
        return Prepared(
            kind=f"device:{req.device_type}",
            name=name,
            path=f"/v1/{family}/{req.device_type}",
            body={"usage": usage} if usage else {},
            query=[("archetype", archetype)] if archetype else [],
            location=location,
            archetype=archetype,
            notes=notes,
        )

    async def _usage(
        self, location_text: str | None, **fields: float | None
    ) -> tuple[dict[str, Any], cat.Location | None]:
        usage: dict[str, Any] = {k: v for k, v in fields.items() if v is not None}
        location = None
        if location_text:
            location = await self.catalog.resolve_location(location_text)
            usage["usage_location"] = location.code
        return usage, location

    # Calling and assembling ------------------------------------------------

    async def _estimate(
        self,
        prepared: Prepared,
        duration_hours: float | None,
        criteria: Sequence[str] | None,
        detail: Detail,
    ) -> EstimateResult:
        checked = await self.catalog.validate_criteria(
            criteria or self.default_criteria
        )
        base = [*prepared.query, ("verbose", "true")]
        if duration_hours is not None:
            base.append(("duration", query_number(duration_hours)))
        impacts_raw, verbose, failed = await self._post(
            prepared.path, base, checked, prepared.body
        )
        known = await self.catalog.criteria()
        parsed = {impact.criterion: impact for impact in parse_impacts(impacts_raw)}
        impacts: list[Impact] = []
        for code in checked:
            if code in parsed:
                impacts.append(parsed[code])
            elif code in failed:
                info = known.get(code)
                impacts.append(
                    Impact(
                        criterion=code,
                        unit=info.unit if info else "",
                        description=info.description if info else "",
                        embedded=Phase(status="upstream_error"),
                        use=Phase(status="upstream_error"),
                    )
                )
        info = parse_verbose(verbose)
        notes = list(prepared.notes)

        duration = Duration(
            hours=duration_hours
            if duration_hours is not None
            else (info.duration_hours or info.lifetime_hours),
            basis="requested" if duration_hours is not None else "full_lifetime",
            lifetime_hours=info.lifetime_hours,
            exceeds_lifetime=bool(
                duration_hours is not None
                and info.lifetime_hours
                and duration_hours > info.lifetime_hours
            ),
        )
        if duration.exceeds_lifetime:
            notes.append(
                f"The period ({number(duration_hours or 0)} h) is longer than the"
                f" hardware lifetime ({number(info.lifetime_hours or 0)} h): embedded"
                " impact covers one unit's full manufacturing; replacement hardware is"
                " not counted."
            )

        location = await self._location(prepared, info.location_code)
        if prepared.location and not prepared.location.exact:
            notes.append(
                f"Location {prepared.location.requested!r} was read as"
                f" {prepared.location.name} ({prepared.location.code})."
            )
        has_use = any(impact.use.status == "ok" for impact in impacts)
        if location.basis == "default_mix" and has_use:
            where = (
                f" ({location.code}, {location.name})"
                if location.code and location.name
                else ""
            )
            notes.append(
                "No location given: the use phase uses BoaviztAPI's default"
                f" electricity mix{where}, so its range is wide. Pass usage_location"
                " for a country-specific figure."
            )

        if prepared.server_parts_given is not None:
            notes.extend(_server_notes(prepared, info.components))
        if failed:
            notes.append(
                f"BoaviztAPI failed (HTTP 500) for: {', '.join(failed)}. The other"
                " criteria are unaffected."
            )

        result = EstimateResult(
            summary="",
            subject=Subject(
                kind=prepared.kind,
                name=prepared.name,
                units=prepared.units,
                provider=prepared.provider,
                requested_as=prepared.requested_as,
            ),
            duration=duration,
            location=location,
            impacts=impacts,
            assumptions=assumptions(info, everything=detail == "breakdown"),
            breakdown=info.components if detail == "breakdown" else None,
            notes=notes,
            api=ApiInfo(
                base_url=self.client.base_url, version=await self.client.version()
            ),
        )
        result.summary = format_estimate(result)
        return result

    async def _post(
        self,
        path: str,
        base: list[tuple[str, str]],
        criteria: list[str],
        body: dict[str, Any],
    ) -> tuple[dict[str, Any], Any, list[str]]:
        """POST all criteria at once; on a 500, retry them one by one."""
        try:
            data = await self.client.post(
                path, [*base, *(("criteria", c) for c in criteria)], body
            )
            return _impacts_of(data), _verbose_of(data), []
        except UpstreamServerError as exc:
            if exc.status != 500 or len(criteria) == 1:
                raise
        results = await asyncio.gather(
            *(self.client.post(path, [*base, ("criteria", c)], body) for c in criteria),
            return_exceptions=True,
        )
        impacts: dict[str, Any] = {}
        verboses: list[Any] = []
        failed: list[str] = []
        for code, outcome in zip(criteria, results, strict=True):
            if isinstance(outcome, UpstreamServerError) and outcome.status == 500:
                failed.append(code)
                continue
            if isinstance(outcome, BaseException):
                raise outcome
            impacts.update(_impacts_of(outcome))
            verboses.append(_verbose_of(outcome))
        if not impacts:
            raise UpstreamServerError(
                500, f"failed for every requested criterion ({', '.join(criteria)})"
            )
        return impacts, merge_verbose(verboses), failed

    async def _location(self, prepared: Prepared, verbose_code: str | None) -> Location:
        if prepared.region:
            return Location(
                code=verbose_code,
                name=await self._country_name(verbose_code),
                basis="region",
                region=prepared.region,
            )
        if prepared.location:
            return Location(
                code=prepared.location.code,
                name=prepared.location.name,
                basis="requested",
            )
        return Location(
            code=verbose_code,
            name=await self._country_name(verbose_code),
            basis="default_mix",
        )

    async def _country_name(self, code: str | None) -> str | None:
        if not code:
            return None
        countries = await self.catalog.countries()
        for name, value in countries.items():
            if value == code:
                return name
        return None


def _read_as(what: str, given: str, resolved: str) -> list[str]:
    """A note when a name was matched to a differently written upstream name."""
    if cat.normalise(given) == cat.normalise(resolved):
        return []
    return [f"{what} {given!r} was read as {resolved}."]


def _server_notes(prepared: Prepared, components: Sequence[Any]) -> list[str]:
    given = prepared.server_parts_given or set()
    if not given:
        return [
            f"No configuration given: every component comes from the archetype"
            f" {prepared.archetype}."
        ]
    present = {component.component.split("-")[0] for component in components}
    filled = sorted(
        part
        for part in present
        if part in CONFIGURABLE_SERVER_PARTS and part not in given
    )
    notes = []
    if filled:
        notes.append(
            f"Not specified, so taken from the archetype {prepared.archetype}:"
            f" {', '.join(filled)}."
        )
    notes.append(
        "Power supply, case, motherboard and assembly always come from the archetype."
    )
    return notes


def _impacts_of(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("impacts"), dict):
        raise UnexpectedResponse("BoaviztAPI returned an estimate without impacts.")
    return data["impacts"]


def _verbose_of(data: Any) -> Any:
    return data.get("verbose") if isinstance(data, dict) else None


def _compare_criterion(
    criterion: str, labels: Sequence[str], results: Sequence[EstimateResult]
) -> CriterionComparison:
    rows: list[ComparisonRow] = []
    unit = ""
    for label, result in zip(labels, results, strict=True):
        impact = next((i for i in result.impacts if i.criterion == criterion), None)
        if impact is None:
            rows.append(
                ComparisonRow(
                    label=label,
                    embedded=None,
                    use=None,
                    total=None,
                    total_min=None,
                    total_max=None,
                    delta_vs_first_pct=None,
                )
            )
            continue
        unit = unit or impact.unit
        total = impact.total
        rows.append(
            ComparisonRow(
                label=label,
                embedded=impact.embedded.value
                if impact.embedded.status == "ok"
                else None,
                use=impact.use.value if impact.use.status == "ok" else None,
                total=total.value if total else None,
                total_min=total.min if total else None,
                total_max=total.max if total else None,
                delta_vs_first_pct=None,
            )
        )
    first = rows[0].total
    for row in rows:
        if row.total is not None and first:
            row.delta_vs_first_pct = round((row.total - first) / first * 100, 1)
    lowest = None
    overlap = None
    if all(row.total is not None for row in rows):
        winner = min(rows, key=lambda row: row.total or 0.0)
        lowest = winner.label
        overlap = any(
            row is not winner
            and row.total_min is not None
            and winner.total_max is not None
            and row.total_min <= winner.total_max
            for row in rows
        )
    return CriterionComparison(
        criterion=criterion, unit=unit, rows=rows, lowest=lowest, ranges_overlap=overlap
    )
