"""Name lists from BoaviztAPI, search over them, and name resolution.

BoaviztAPI matches some names fuzzily on its own and accepts unknown locations
without complaint, so every name and location is resolved here first and the
exact upstream string is sent.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from boaviztapi_mcp.client import BoaviztaClient
from boaviztapi_mcp.errors import InputError, UnexpectedResponse

CatalogKind = Literal[
    "cloud_provider",
    "cloud_instance",
    "cloud_region",
    "server_archetype",
    "device_archetype",
    "gpu",
    "cpu",
    "country",
]

DeviceType = Literal[
    "laptop",
    "desktop",
    "smartphone",
    "tablet",
    "television",
    "box",
    "vr_headset",
    "monitor",
    "usb_stick",
    "external_ssd",
    "external_hdd",
    "vr_controller",
    "iot_device",
]

DEVICE_FAMILIES: dict[str, str] = {
    "laptop": "terminal",
    "desktop": "terminal",
    "smartphone": "terminal",
    "tablet": "terminal",
    "television": "terminal",
    "box": "terminal",
    "vr_headset": "terminal",
    "monitor": "peripheral",
    "usb_stick": "peripheral",
    "external_ssd": "peripheral",
    "external_hdd": "peripheral",
    "vr_controller": "peripheral",
    "iot_device": "iot",
}

# Common ways of naming a country that the API's list does not contain.
COUNTRY_ALIASES: dict[str, str] = {
    "us": "USA",
    "america": "USA",
    "united states of america": "USA",
    "uk": "GBR",
    "great britain": "GBR",
    "britain": "GBR",
    "south korea": "KOR",
    "russia": "RUS",
    "uae": "ARE",
}

MAX_CANDIDATES = 8
MAX_SUGGESTIONS = 5

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def normalise(text: str) -> str:
    """Lower-case and collapse punctuation to single spaces."""
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def rank(query: str, names: Sequence[str]) -> list[str]:
    """Order ``names`` by how well they match ``query``; drop poor matches.

    Order: exact, prefix, every query word as a whole word, every query word as
    a substring, then close spellings (difflib ratio >= 0.6).
    """
    q = normalise(query)
    if not q:
        return list(names)
    q_tokens = q.split()
    scored: list[tuple[int, float, int, int, str]] = []
    for index, name in enumerate(names):
        n = normalise(name)
        n_tokens = n.split()
        if n == q:
            tier, score = 0, 0.0
        elif n.startswith(q):
            tier, score = 1, 0.0
        elif all(t in n_tokens for t in q_tokens):
            tier, score = 2, 0.0
        elif all(t in n for t in q_tokens):
            tier, score = 3, 0.0
        else:
            ratio = difflib.SequenceMatcher(None, q, n).ratio()
            if ratio < 0.6:
                continue
            tier, score = 4, -ratio
        scored.append((tier, score, len(name), index, name))
    scored.sort()
    return [entry[-1] for entry in scored]


def resolve(query: str, names: Sequence[str], *, what: str, hint: str) -> str:
    """Return the single upstream name meant by ``query`` or raise InputError."""
    text = query.strip()
    if not text:
        raise InputError(f"An empty {what} was given. {hint}")
    for name in names:
        if name == text:
            return name
    lowered = [name for name in names if name.lower() == text.lower()]
    if len(lowered) == 1:
        return lowered[0]

    q = normalise(text)
    q_tokens = q.split()
    exact = [name for name in names if normalise(name) == q]
    if len(exact) == 1:
        return exact[0]
    whole = [
        name for name in names if all(t in normalise(name).split() for t in q_tokens)
    ]
    if len(whole) == 1:
        return whole[0]
    if len(whole) > 1:
        raise _ambiguous(text, whole, what, hint)
    partial = [name for name in names if all(t in normalise(name) for t in q_tokens)]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise _ambiguous(text, partial, what, hint)

    close = rank(text, names)[:MAX_SUGGESTIONS]
    suggestion = f" Close matches: {', '.join(close)}." if close else ""
    raise InputError(f"Unknown {what} {text!r}.{suggestion} {hint}")


def _ambiguous(text: str, matches: Sequence[str], what: str, hint: str) -> InputError:
    shown = list(matches[:MAX_CANDIDATES])
    more = len(matches) - len(shown)
    tail = f" and {more} more" if more > 0 else ""
    return InputError(
        f"{what[:1].upper()}{what[1:]} {text!r} matches {len(matches)} names: "
        f"{', '.join(shown)}{tail}. Use one of the exact names. {hint}"
    )


@dataclass(frozen=True)
class SearchHits:
    names: list[str]
    total: int


@dataclass(frozen=True)
class Criterion:
    code: str
    name: str
    unit: str
    description: str
    method: str | None


@dataclass(frozen=True)
class Location:
    code: str
    name: str


class Catalog:
    """Cached name lists and the resolution rules built on top of them."""

    def __init__(self, client: BoaviztaClient) -> None:
        self.client = client

    # Lists -----------------------------------------------------------------

    async def gpu_names(self) -> list[str]:
        return _strings(await self.client.get("/v1/utils/gpu_name"), "GPU names")

    async def cpu_names(self) -> list[str]:
        return _strings(await self.client.get("/v1/utils/cpu_name"), "CPU names")

    async def providers(self) -> list[str]:
        return _strings(
            await self.client.get("/v1/cloud/instance/all_providers"), "providers"
        )

    async def instances(self, provider: str) -> list[str]:
        provider = await self.resolve_provider(provider)
        return _strings(
            await self.client.get(
                "/v1/cloud/instance/all_instances", [("provider", provider)]
            ),
            "instances",
        )

    async def regions(self, provider: str | None = None) -> list[tuple[str, str]]:
        raw = await self.client.get("/v1/utils/cloud_regions")
        if not isinstance(raw, list):
            raise UnexpectedResponse("BoaviztAPI returned an unexpected region list.")
        pairs = [
            (str(item["provider"]), str(item["region"]))
            for item in raw
            if isinstance(item, dict) and "provider" in item and "region" in item
        ]
        if provider is not None:
            provider = await self.resolve_provider(provider)
            pairs = [pair for pair in pairs if pair[0] == provider]
        return pairs

    async def server_archetypes(self) -> list[str]:
        return _strings(
            await self.client.get("/v1/server/archetypes"), "server archetypes"
        )

    async def device_archetypes(self, device_type: str) -> list[str]:
        family = device_family(device_type)
        return _strings(
            await self.client.get(f"/v1/{family}/{device_type}/archetypes"),
            f"{device_type} archetypes",
        )

    async def countries(self) -> dict[str, str]:
        """Country or region name to code, e.g. ``{"France": "FRA"}``."""
        raw = await self.client.get("/v1/utils/country_code")
        if not isinstance(raw, dict):
            raise UnexpectedResponse("BoaviztAPI returned an unexpected country list.")
        return {str(name): str(code) for name, code in raw.items()}

    async def criteria(self) -> dict[str, Criterion]:
        raw = await self.client.get("/v1/utils/impact_criteria")
        if not isinstance(raw, dict):
            raise UnexpectedResponse("BoaviztAPI returned an unexpected criteria list.")
        result: dict[str, Criterion] = {}
        for code, info in raw.items():
            info = info if isinstance(info, dict) else {}
            result[str(code)] = Criterion(
                code=str(code),
                name=str(info.get("name") or code),
                unit=str(info.get("unit") or ""),
                description=str(info.get("description") or ""),
                method=str(info["method"]) if info.get("method") else None,
            )
        return result

    # Search ----------------------------------------------------------------

    async def search(
        self,
        kind: CatalogKind,
        query: str | None = None,
        *,
        provider: str | None = None,
        device_type: str | None = None,
        limit: int = 20,
    ) -> SearchHits:
        names = await self._names_for(kind, provider=provider, device_type=device_type)
        matches = rank(query, names) if query and query.strip() else names
        return SearchHits(names=matches[:limit], total=len(matches))

    async def _names_for(
        self, kind: CatalogKind, *, provider: str | None, device_type: str | None
    ) -> list[str]:
        if kind == "cloud_provider":
            return await self.providers()
        if kind == "cloud_instance":
            if not provider:
                raise InputError(
                    "Searching cloud instances needs a provider. Call"
                    " search_catalog(kind='cloud_provider') to list them."
                )
            return await self.instances(provider)
        if kind == "cloud_region":
            pairs = await self.regions(provider)
            if provider:
                return [region for _, region in pairs]
            return [f"{prov}: {region}" for prov, region in pairs]
        if kind == "server_archetype":
            return await self.server_archetypes()
        if kind == "device_archetype":
            if not device_type:
                raise InputError(
                    "Searching device archetypes needs a device_type, for example"
                    " 'laptop' or 'iot_device'."
                )
            return await self.device_archetypes(device_type)
        if kind == "gpu":
            return await self.gpu_names()
        if kind == "cpu":
            return await self.cpu_names()
        if kind == "country":
            return [
                f"{name} ({code})" for name, code in (await self.countries()).items()
            ]
        raise InputError(f"Unknown catalog kind {kind!r}.")  # pragma: no cover

    # Resolution ------------------------------------------------------------

    async def resolve_provider(self, provider: str) -> str:
        providers = _strings(
            await self.client.get("/v1/cloud/instance/all_providers"), "providers"
        )
        wanted = provider.strip().lower()
        for name in providers:
            if name.lower() == wanted:
                return name
        raise InputError(
            f"Unknown cloud provider {provider!r}. Available: {', '.join(providers)}."
        )

    async def resolve_instance(self, provider: str, instance_type: str) -> str:
        provider = await self.resolve_provider(provider)
        return resolve(
            instance_type,
            await self.instances(provider),
            what=f"{provider} instance type",
            hint=(
                f"Call search_catalog(kind='cloud_instance', provider='{provider}',"
                " query=...) to find valid names."
            ),
        )

    async def resolve_region(self, provider: str, region: str) -> str:
        provider = await self.resolve_provider(provider)
        regions = [name for _, name in await self.regions(provider)]
        return resolve(
            region,
            regions,
            what=f"{provider} region",
            hint=(
                f"Call search_catalog(kind='cloud_region', provider='{provider}')"
                " to list them, or pass usage_location instead."
            ),
        )

    async def resolve_gpu(self, name: str) -> str:
        return resolve(
            name,
            await self.gpu_names(),
            what="GPU",
            hint="Call search_catalog(kind='gpu', query=...) to find valid names.",
        )

    async def resolve_cpu(self, name: str) -> str:
        return resolve(
            name,
            await self.cpu_names(),
            what="CPU",
            hint="Call search_catalog(kind='cpu', query=...) to find valid names.",
        )

    async def resolve_server_archetype(self, name: str) -> str:
        return resolve(
            name,
            await self.server_archetypes(),
            what="server archetype",
            hint="Call search_catalog(kind='server_archetype') to list them.",
        )

    async def resolve_device_archetype(self, device_type: str, name: str) -> str:
        return resolve(
            name,
            await self.device_archetypes(device_type),
            what=f"{device_type} archetype",
            hint=(
                "Call search_catalog(kind='device_archetype',"
                f" device_type='{device_type}') to list them."
            ),
        )

    async def resolve_location(self, text: str) -> Location:
        countries = await self.countries()
        by_code = {code: name for name, code in countries.items()}
        value = text.strip()
        if value.upper() in by_code:
            code = value.upper()
            return Location(code=code, name=by_code[code])
        alias = COUNTRY_ALIASES.get(normalise(value))
        if alias and alias in by_code:
            return Location(code=alias, name=by_code[alias])
        name = resolve(
            value,
            list(countries),
            what="location",
            hint=(
                "Use a country name or its 3-letter code (e.g. 'France' or 'FRA'),"
                " 'WOR' for the world average or 'EEE' for Europe. Call"
                " search_catalog(kind='country', query=...) to look one up."
            ),
        )
        return Location(code=countries[name], name=name)

    async def validate_criteria(self, requested: Sequence[str]) -> list[str]:
        known = await self.criteria()
        lowered = {code.lower(): code for code in known}
        result: list[str] = []
        for raw in requested:
            text = raw.strip()
            if text.lower() == "all":
                raise InputError(
                    "criteria='all' is not supported (BoaviztAPI fails on it). Pass a"
                    " list of codes; call list_impact_criteria to see all of them."
                )
            code = lowered.get(text.lower())
            if code is None:
                raise InputError(
                    f"Unknown impact criterion {raw!r}. Valid codes:"
                    f" {', '.join(known)}. Call list_impact_criteria for details."
                )
            if code not in result:
                result.append(code)
        if not result:
            raise InputError("At least one impact criterion is needed, e.g. 'gwp'.")
        return result


def device_family(device_type: str) -> str:
    try:
        return DEVICE_FAMILIES[device_type]
    except KeyError:
        raise InputError(
            f"Unknown device type {device_type!r}. Valid types:"
            f" {', '.join(DEVICE_FAMILIES)}."
        ) from None


def _strings(raw: Any, what: str) -> list[str]:
    if not isinstance(raw, list):
        raise UnexpectedResponse(f"BoaviztAPI returned an unexpected list of {what}.")
    return [str(item) for item in raw]


DescribeKind = Literal[
    "cloud_instance", "server_archetype", "device_archetype", "gpu", "cpu"
]


async def describe(
    catalog: Catalog,
    kind: DescribeKind,
    name: str,
    *,
    provider: str | None = None,
    device_type: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return the exact name and the API's configuration for one catalog item."""
    client = catalog.client
    if kind == "cloud_instance":
        if not provider:
            raise InputError("Describing a cloud instance needs a provider.")
        provider = await catalog.resolve_provider(provider)
        resolved = await catalog.resolve_instance(provider, name)
        raw = await client.get(
            "/v1/cloud/instance/instance_config",
            [("provider", provider), ("instance_type", resolved)],
        )
        return f"{provider} {resolved}", tidy_config(raw)
    if kind == "server_archetype":
        resolved = await catalog.resolve_server_archetype(name)
        raw = await client.get("/v1/server/archetype_config", [("archetype", resolved)])
        return resolved, tidy_config(raw)
    if kind == "device_archetype":
        if not device_type:
            raise InputError("Describing a device archetype needs a device_type.")
        family = device_family(device_type)
        resolved = await catalog.resolve_device_archetype(device_type, name)
        raw = await client.get(
            f"/v1/{family}/{device_type}/archetype_config", [("archetype", resolved)]
        )
        return resolved, tidy_config(raw)
    if kind == "gpu":
        resolved = await catalog.resolve_gpu(name)
        raw = await client.get("/v1/utils/name_to_gpu", [("gpu_name", resolved)])
        return resolved, tidy_config(raw)
    resolved = await catalog.resolve_cpu(name)
    raw = await client.get("/v1/utils/name_to_cpu", [("cpu_name", resolved)])
    return resolved, tidy_config(raw)


def tidy_config(raw: Any) -> dict[str, Any]:
    """Drop empty values and collapse ``{"default": x}`` to ``x``."""
    if not isinstance(raw, dict):
        raise UnexpectedResponse(f"BoaviztAPI returned {raw!r} instead of details.")
    cleaned = _tidy(raw)
    return cleaned if isinstance(cleaned, dict) else {}


def _tidy(value: Any) -> Any:
    if isinstance(value, dict):
        items = {k: _tidy(v) for k, v in value.items()}
        items = {k: v for k, v in items.items() if v not in (None, {}, [])}
        if set(items) == {"default"}:
            return items["default"]
        return items
    if isinstance(value, list):
        return [_tidy(v) for v in value]
    return value
