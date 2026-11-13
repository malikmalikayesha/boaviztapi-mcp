"""The MCP server: tool definitions on top of the catalog and estimator.

This is the only module that imports the MCP SDK.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal, TypeVar

import httpx2
from mcp.server.caching import CacheableMethod, CacheHint
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from boaviztapi_mcp import __version__
from boaviztapi_mcp.catalog import (
    Catalog,
    CatalogKind,
    DescribeKind,
    DeviceType,
    describe,
    normalise,
)
from boaviztapi_mcp.client import BoaviztaClient
from boaviztapi_mcp.config import Settings
from boaviztapi_mcp.errors import BoaviztaError
from boaviztapi_mcp.estimates import CompareItem, EstimateRequest, Estimator
from boaviztapi_mcp.formatting import number
from boaviztapi_mcp.models import (
    CatalogItem,
    CloudInstanceRequest,
    ComparisonResult,
    ComponentKind,
    ComponentRequest,
    CpuSpec,
    CriteriaList,
    CriterionInfo,
    Detail,
    DeviceRequest,
    DiskSpec,
    EstimateResult,
    GpuSpec,
    RamSpec,
    SearchResult,
    ServerRequest,
)

INSTRUCTIONS = """\
Tools for estimating the environmental footprint of IT hardware with BoaviztAPI
(https://doc.api.boavizta.org): cloud instances, servers, single components such as
GPUs, and end-user devices. All numbers come from BoaviztAPI.

When reporting results:
1. Keep every number with its unit exactly as returned (kgCO2eq, MJ, kgSbeq, m3 eq.).
2. Report embedded (manufacturing) and use (electricity) impacts separately; only
   give a total when the result has one.
3. Always state the period. Without duration_hours the figures cover the whole
   lifetime. With it, embedded is the share of manufacturing for that period.
4. Give ranges as min to max when they differ; do not round further or recompute.
5. Repeat warnings and notes next to the figures they belong to.
6. "not available from BoaviztAPI for this item" means no data, never zero.
7. Without a location the use phase relies on a default mix with a wide range;
   suggest a country.
8. Name the exact item and the main assumptions (lifetime, average power, load).
9. Cite the BoaviztAPI version and URL from the result.
Use search_catalog to find exact names before estimating when unsure.
"""

DESCRIPTION = (
    "Estimate the environmental footprint (carbon, resources, energy and more) of"
    " cloud instances, servers, GPUs and other components, and end-user devices"
    " with BoaviztAPI."
)

# The tool list never changes while the server runs, and is the same for every
# client, so clients and intermediaries may cache it for a day.
STATIC_LIST = CacheHint(ttl_ms=24 * 60 * 60 * 1000, scope="public")
CACHE_HINTS: dict[CacheableMethod, CacheHint] = {
    "tools/list": STATIC_LIST,
    "prompts/list": STATIC_LIST,
    "resources/list": STATIC_LIST,
    "resources/templates/list": STATIC_LIST,
}

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)

T = TypeVar("T")

DurationHours = Annotated[
    float | None,
    Field(
        gt=0,
        description="Period assessed in hours (8760 = 1 year, 730 = 1 month)."
        " Omit for the whole hardware lifetime.",
    ),
]
UsageLocation = Annotated[
    str | None,
    Field(
        description="Where the electricity comes from: country name or 3-letter code"
        " ('Germany', 'DEU'), 'WOR' for world or 'EEE' for Europe.",
    ),
]
Criteria = Annotated[
    list[str] | None,
    Field(
        description="Impact criteria codes; default gwp, adp, pe."
        " See list_impact_criteria. 'all' is not accepted.",
    ),
]
DetailLevel = Annotated[
    Detail,
    Field(description="'breakdown' adds per-component impacts and all assumptions."),
]
LifetimeHours = Annotated[
    float | None, Field(gt=0, description="Hardware lifetime in hours.")
]
AvgPower = Annotated[float | None, Field(gt=0, description="Average power in watts.")]
LoadPercent = Annotated[
    float | None, Field(ge=0, le=100, description="Average CPU load in percent.")
]
GpuLoadPercent = Annotated[
    float | None, Field(ge=0, le=100, description="Average GPU load in percent.")
]
UseTimeRatio = Annotated[
    float | None,
    Field(ge=0, le=1, description="Share of time the device is in use, 0 to 1."),
]


class CompareItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(description="Short unique name for this option.")
    kind: Literal["cloud_instance", "server", "component", "device"] = Field(
        description="Which estimate tool's inputs params holds."
    )
    params: dict[str, Any] = Field(
        description="The inputs of the matching estimate tool, without duration_hours,"
        " criteria and detail. cloud_instance: provider, instance_type, region or"
        " usage_location, load_percent. server: archetype, server_type, cpu, ram,"
        " disks, gpu, avg_power_w, load_percent, gpu_load_percent, use_time_ratio,"
        " lifetime_hours, usage_location. component: component, name, units,"
        " capacity_gb, tdp_w, avg_power_w, load_percent, lifetime_hours,"
        " usage_location. device: device_type, archetype, avg_power_w,"
        " use_time_ratio, lifetime_hours, usage_location."
    )


COMPARE_MODELS: dict[str, type[BaseModel]] = {
    "cloud_instance": CloudInstanceRequest,
    "server": ServerRequest,
    "component": ComponentRequest,
    "device": DeviceRequest,
}


class App:
    """Shared state for one server: the HTTP client, catalog and estimator."""

    def __init__(
        self, settings: Settings, transport: httpx2.AsyncBaseTransport | None
    ) -> None:
        self.settings = settings
        self.client = BoaviztaClient(settings, transport=transport)
        self.catalog = Catalog(self.client)
        self.estimator = Estimator(
            self.client, self.catalog, default_criteria=settings.default_criteria
        )


async def _guard(call: Awaitable[T]) -> T:
    """Turn expected failures into tool errors with a useful message."""
    try:
        return await call
    except BoaviztaError as exc:
        raise ToolError(str(exc)) from exc
    except ValidationError as exc:
        raise ToolError(_validation_message(exc)) from exc


def _validation_message(exc: ValidationError) -> str:
    problems = []
    for error in exc.errors():
        where = ".".join(str(part) for part in error["loc"])
        problems.append(f"{where}: {error['msg']}" if where else error["msg"])
    return "Invalid input: " + "; ".join(problems)


def create_server(
    settings: Settings | None = None,
    *,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> MCPServer:
    """Build the server. ``transport`` replaces HTTP in tests."""
    # httpx2 logs every request at INFO; keep MCP client logs readable.
    for name in ("httpx2", "httpcore2", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    app = App(settings or Settings.from_env(), transport)

    @asynccontextmanager
    async def lifespan(_: MCPServer[Any]) -> AsyncIterator[None]:
        try:
            yield None
        finally:
            await app.client.aclose()

    server: MCPServer[Any] = MCPServer(
        "boaviztapi",
        title="BoaviztAPI",
        description=DESCRIPTION,
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://github.com/malikmalikayesha/boaviztapi-mcp",
        lifespan=lifespan,
        cache_hints=CACHE_HINTS,
        # No change notifications are ever sent: the tool list is fixed.
        subscriptions=False,
    )
    tool = _tool_decorator(server)

    @tool(title="List impact criteria")
    async def list_impact_criteria(
        query: Annotated[
            str | None,
            Field(description="Optional filter on code or description, e.g. 'water'."),
        ] = None,
    ) -> CriteriaList:
        """List BoaviztAPI's impact criteria with their code, unit and meaning, e.g.
        gwp (climate change, kgCO2eq), adp (abiotic resources, kgSbeq) or pe
        (primary energy, MJ).

        Use it to explain a code that appears in a result, or to choose `criteria`
        for the estimate tools; it estimates nothing. `query` filters on code, unit
        or description words such as 'water'. Read-only; the list comes from
        BoaviztAPI and is cached for a day.
        """

        async def run() -> CriteriaList:
            known = await app.catalog.criteria()
            items = list(known.values())
            if query and query.strip():
                needle = normalise(query)
                items = [
                    c
                    for c in items
                    if needle in normalise(f"{c.code} {c.description} {c.unit}")
                ]
            lines = [f"{c.code}: {c.description} ({c.unit})" for c in items]
            summary = "\n".join(lines) if lines else f"No criterion matches {query!r}."
            return CriteriaList(
                summary=summary,
                criteria=[
                    CriterionInfo(
                        code=c.code,
                        unit=c.unit,
                        description=c.description,
                        method=c.method,
                    )
                    for c in items
                ],
            )

        return await _guard(run())

    @tool(title="Search the BoaviztAPI catalog")
    async def search_catalog(
        kind: Annotated[CatalogKind, Field(description="What to search.")],
        query: Annotated[
            str | None,
            Field(description="Words to match, e.g. 'h100', 'm5.x', 'germ'."),
        ] = None,
        provider: Annotated[
            str | None,
            Field(
                description="Cloud provider; required for cloud_instance, optional"
                " for cloud_region."
            ),
        ] = None,
        device_type: Annotated[
            DeviceType | None,
            Field(description="Required for device_archetype."),
        ] = None,
        limit: Annotated[
            int, Field(ge=1, le=100, description="Maximum names to return.")
        ] = 20,
    ) -> SearchResult:
        """Find the exact names BoaviztAPI knows, before estimating.

        Use it whenever an estimate needs a name you are unsure of: a GPU or CPU
        model, a cloud instance type (needs `provider`), a cloud region, a server or
        device archetype (needs `device_type`), or a country. Results are exact
        upstream strings, including upstream typos such as
        'platfom_gpucompute_high', best matches first and capped by `limit`;
        `total_matches` says how many exist. To see what one item contains, use
        describe_catalog_item instead. Read-only; lists are cached for a day.
        """

        async def run() -> SearchResult:
            hits = await app.catalog.search(
                kind, query, provider=provider, device_type=device_type, limit=limit
            )
            shown = ", ".join(hits.names) if hits.names else "nothing found"
            noun = "match" if hits.total == 1 else "matches"
            more = (
                f" (showing {len(hits.names)} of {hits.total})"
                if hits.total > len(hits.names)
                else ""
            )
            return SearchResult(
                summary=f"{hits.total} {kind} {noun}{more}: {shown}",
                kind=kind,
                query=query,
                total_matches=hits.total,
                names=hits.names,
            )

        return await _guard(run())

    @tool(title="Describe a catalog item")
    async def describe_catalog_item(
        kind: Annotated[DescribeKind, Field(description="What kind of item.")],
        name: Annotated[str, Field(description="Name as found with search_catalog.")],
        provider: Annotated[
            str | None, Field(description="Required for cloud_instance.")
        ] = None,
        device_type: Annotated[
            DeviceType | None, Field(description="Required for device_archetype.")
        ] = None,
    ) -> CatalogItem:
        """Show what a named catalog item contains: a cloud instance's vCPUs, memory
        and host platform; a server or device archetype's default parts and usage;
        or a GPU's or CPU's specifications.

        Use it to explain or check the assumptions behind an estimate, or to choose
        between similar items; it does not estimate impacts. `name` is resolved to
        the exact upstream name, and an ambiguous name returns the candidates (use
        search_catalog to find names). `provider` is required for cloud_instance and
        `device_type` for device_archetype. Read-only; cached for a day.
        """

        async def run() -> CatalogItem:
            resolved, details = await describe(
                app.catalog, kind, name, provider=provider, device_type=device_type
            )
            lines = [f"{kind} {resolved}"]
            lines.extend(f"{key}: {_inline(value)}" for key, value in details.items())
            return CatalogItem(
                summary="\n".join(lines), kind=kind, name=resolved, details=details
            )

        return await _guard(run())

    @tool(title="Estimate a cloud instance")
    async def estimate_cloud_instance(
        provider: Annotated[str, Field(description="Cloud provider, e.g. 'aws'.")],
        instance_type: Annotated[
            str, Field(description="Instance type, e.g. 'm5.xlarge'.")
        ],
        region: Annotated[
            str | None,
            Field(
                description="Provider region such as 'eu-west-3'; exclusive with"
                " usage_location."
            ),
        ] = None,
        usage_location: UsageLocation = None,
        load_percent: LoadPercent = None,
        duration_hours: DurationHours = None,
        criteria: Criteria = None,
        detail: DetailLevel = "summary",
    ) -> EstimateResult:
        """Estimate the environmental footprint of one cloud VM: its share of the host
        server's manufacturing (embedded) and the electricity it uses (use), per
        impact criterion, with units, min-max ranges and warnings.

        Use it for a single instance; use compare_estimates to rank several and
        estimate_server for physical servers. Give either `region` (the provider's
        region, which fixes the electricity mix) or `usage_location` (a country),
        not both; with neither, a wide European default is used. `duration_hours`
        sets the period (8760 = one year); omit it for the whole hardware lifetime.
        Read-only: one BoaviztAPI request, cached for an hour; if one criterion
        fails upstream the others are still returned. Use
        search_catalog(kind='cloud_instance', provider=...) if unsure of a name.
        """
        return await _guard(
            app.estimator.run(
                CloudInstanceRequest(
                    provider=provider,
                    instance_type=instance_type,
                    region=region,
                    usage_location=usage_location,
                    load_percent=load_percent,
                ),
                duration_hours=duration_hours,
                criteria=criteria,
                detail=detail,
            )
        )

    @tool(title="Estimate a server")
    async def estimate_server(
        archetype: Annotated[
            str | None,
            Field(
                description="Server archetype for anything not given (default"
                " 'platform_compute_medium'); see search_catalog."
            ),
        ] = None,
        server_type: Annotated[
            Literal["rack", "blade"] | None,
            Field(description="Form factor; defaults to the archetype's (rack)."),
        ] = None,
        cpu: Annotated[
            CpuSpec | None,
            Field(description="CPUs, e.g. {name: 'Xeon Gold 6134', units: 2}."),
        ] = None,
        ram: Annotated[
            list[RamSpec] | None,
            Field(description="RAM modules, e.g. [{units: 12, capacity_gb: 32}]."),
        ] = None,
        disks: Annotated[
            list[DiskSpec] | None,
            Field(
                description="Disks, e.g. [{type: 'ssd', units: 2, capacity_gb: 960}]."
            ),
        ] = None,
        gpu: Annotated[
            GpuSpec | None,
            Field(description="GPUs, e.g. {name: 'A100 SXM4 80GB', units: 8}."),
        ] = None,
        avg_power_w: AvgPower = None,
        load_percent: LoadPercent = None,
        gpu_load_percent: GpuLoadPercent = None,
        use_time_ratio: UseTimeRatio = None,
        lifetime_hours: LifetimeHours = None,
        usage_location: UsageLocation = None,
        duration_hours: DurationHours = None,
        criteria: Criteria = None,
        detail: DetailLevel = "summary",
    ) -> EstimateResult:
        """Estimate the environmental footprint of an on-premise server, optionally
        with GPUs: manufacturing (embedded) and electricity (use) impacts per
        criterion, with units, ranges and warnings.

        Use it for physical servers; use estimate_cloud_instance for cloud VMs and
        estimate_component for one part on its own. Any part you leave out (CPU,
        RAM, disks, GPU, power supply, case) comes from `archetype` (default
        'platform_compute_medium'), and the result lists which ones. The default
        lifetime is 4 years (35040 h); a `duration_hours` longer than the lifetime
        counts manufacturing once and says so. Set `usage_location` for a country's
        electricity mix and detail='breakdown' for per-component impacts.
        Read-only: one BoaviztAPI request, cached for an hour.
        """
        return await _guard(
            app.estimator.run(
                ServerRequest(
                    archetype=archetype,
                    server_type=server_type,
                    cpu=cpu,
                    ram=ram,
                    disks=disks,
                    gpu=gpu,
                    avg_power_w=avg_power_w,
                    load_percent=load_percent,
                    gpu_load_percent=gpu_load_percent,
                    use_time_ratio=use_time_ratio,
                    lifetime_hours=lifetime_hours,
                    usage_location=usage_location,
                ),
                duration_hours=duration_hours,
                criteria=criteria,
                detail=detail,
            )
        )

    @tool(title="Estimate a component")
    async def estimate_component(
        component: Annotated[ComponentKind, Field(description="Component type.")],
        name: Annotated[
            str | None,
            Field(description="Model name for gpu or cpu, e.g. 'H100 SXM'."),
        ] = None,
        units: Annotated[int, Field(ge=1, description="How many.")] = 1,
        capacity_gb: Annotated[
            int | None, Field(gt=0, description="Capacity in GB (ram, ssd, hdd).")
        ] = None,
        tdp_w: Annotated[
            float | None, Field(gt=0, description="TDP in watts (gpu, cpu).")
        ] = None,
        avg_power_w: AvgPower = None,
        load_percent: LoadPercent = None,
        lifetime_hours: LifetimeHours = None,
        usage_location: UsageLocation = None,
        duration_hours: DurationHours = None,
        criteria: Criteria = None,
        detail: DetailLevel = "summary",
    ) -> EstimateResult:
        """Estimate the environmental footprint of one kind of component (gpu, cpu,
        ram, ssd or hdd), `units` of it: manufacturing (embedded) and electricity
        (use) impacts per criterion, with units, ranges and warnings.

        Use it for parts on their own, such as eight H100 GPUs. A GPU alone excludes
        its host server: for a whole machine use estimate_server with a `gpu` block.
        `name` and `tdp_w` apply to gpu and cpu, `capacity_gb` to ram, ssd and hdd;
        other combinations are an error. Names are resolved to BoaviztAPI's model
        names and an ambiguous one (such as 'h100') returns the candidates.
        Read-only: one BoaviztAPI request, cached for an hour.
        """
        return await _guard(
            app.estimator.run(
                ComponentRequest(
                    component=component,
                    name=name,
                    units=units,
                    capacity_gb=capacity_gb,
                    tdp_w=tdp_w,
                    avg_power_w=avg_power_w,
                    load_percent=load_percent,
                    lifetime_hours=lifetime_hours,
                    usage_location=usage_location,
                ),
                duration_hours=duration_hours,
                criteria=criteria,
                detail=detail,
            )
        )

    @tool(title="Estimate an end-user device")
    async def estimate_device(
        device_type: Annotated[DeviceType, Field(description="Kind of device.")],
        archetype: Annotated[
            str | None,
            Field(
                description="Device archetype, e.g. 'laptop-pro'; required for"
                " iot_device. See search_catalog(kind='device_archetype')."
            ),
        ] = None,
        avg_power_w: AvgPower = None,
        use_time_ratio: UseTimeRatio = None,
        lifetime_hours: LifetimeHours = None,
        usage_location: UsageLocation = None,
        duration_hours: DurationHours = None,
        criteria: Criteria = None,
        detail: DetailLevel = "summary",
    ) -> EstimateResult:
        """Estimate the environmental footprint of an end-user device: laptop,
        desktop, smartphone, tablet, television, box, vr_headset, vr_controller,
        monitor, usb_stick, external_ssd, external_hdd or iot_device. Returns
        manufacturing (embedded) and electricity (use) impacts per criterion, with
        units, ranges and warnings.

        Use it for devices people use, not servers or cloud (see estimate_server and
        estimate_cloud_instance). Without `archetype` the device type's default
        profile is used, except for iot_device, which needs one; list them with
        search_catalog(kind='device_archetype', device_type=...). `use_time_ratio`
        is the share of time the device is on (0 to 1). Criteria without data are
        reported as not available, never as 0. Read-only: one BoaviztAPI request,
        cached for an hour.
        """
        return await _guard(
            app.estimator.run(
                DeviceRequest(
                    device_type=device_type,
                    archetype=archetype,
                    avg_power_w=avg_power_w,
                    use_time_ratio=use_time_ratio,
                    lifetime_hours=lifetime_hours,
                    usage_location=usage_location,
                ),
                duration_hours=duration_hours,
                criteria=criteria,
                detail=detail,
            )
        )

    @tool(title="Compare estimates")
    async def compare_estimates(
        items: Annotated[
            list[CompareItemInput],
            Field(min_length=2, max_length=5, description="2 to 5 options."),
        ],
        duration_hours: Annotated[
            float,
            Field(
                gt=0,
                description="Common period in hours for every option (8760 = 1"
                " year), so options with different lifetimes compare fairly.",
            ),
        ],
        criteria: Criteria = None,
    ) -> ComparisonResult:
        """Compare 2 to 5 options (cloud instances, servers, components or devices)
        over one common period and rank them per criterion, with each total, the
        difference from the first option, and whether the uncertainty ranges overlap.

        Use it whenever the question is which option is greener or how options
        differ; use the single estimate tools for one item. Each item has a `label`,
        a `kind`, and `params` holding the matching estimate tool's inputs (without
        duration_hours, criteria or detail). `duration_hours` is required so items
        with different lifetimes compare on equal terms. Every item is checked
        before any estimate runs, and an invalid item fails the call with its label
        named. Read-only: one BoaviztAPI request per item.
        """

        async def run() -> ComparisonResult:
            compare_items = [
                CompareItem(item.label, _compare_request(item)) for item in items
            ]
            return await app.estimator.compare(
                compare_items, duration_hours=duration_hours, criteria=criteria
            )

        return await _guard(run())

    return server


def _compare_request(item: CompareItemInput) -> EstimateRequest:
    model = COMPARE_MODELS[item.kind]
    try:
        request = model.model_validate(item.params)
    except ValidationError as exc:
        raise BoaviztaError(
            f"Item {item.label!r} ({item.kind}): {_validation_message(exc)}"
        ) from exc
    assert isinstance(
        request, (CloudInstanceRequest, ServerRequest, ComponentRequest, DeviceRequest)
    )
    return request


Decorator = Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]


def _tool_decorator(server: MCPServer[Any]) -> Callable[..., Decorator]:
    """``@tool(title=...)``: register a read-only tool with a display title."""

    def tool(*, title: str) -> Decorator:
        annotations = READ_ONLY.model_copy(update={"title": title})
        return server.tool(title=title, annotations=annotations)

    return tool


def _inline(value: Any) -> str:
    if isinstance(value, float):
        return number(value)
    if isinstance(value, dict):
        return ", ".join(f"{k} {_inline(v)}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(_inline(v) for v in value)
    return str(value)


def run(settings: Settings | None = None) -> None:
    """Run the server on stdio."""
    create_server(settings).run("stdio")
