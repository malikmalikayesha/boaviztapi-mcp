import pytest

from boaviztapi_mcp.catalog import Catalog, normalise, rank, resolve
from boaviztapi_mcp.errors import InputError

pytestmark = pytest.mark.anyio

GPUS = ["NVIDIA H100 SXM 80GB", "NVIDIA H100 PCIe 80GB", "NVIDIA A100 SXM4 80GB"]


def test_normalise() -> None:
    assert normalise("  NVIDIA H100-SXM (80GB) ") == "nvidia h100 sxm 80gb"


def test_rank_orders_exact_prefix_words_substring_then_spelling() -> None:
    names = ["m5.xlarge", "m5.2xlarge", "m5d.xlarge", "c5.xlarge", "m5.large"]
    assert rank("m5.xlarge", names)[0] == "m5.xlarge"
    assert rank("m5", names)[:3] == ["m5.large", "m5.xlarge", "m5.2xlarge"]
    assert "c5.xlarge" not in rank("m5 xlarge", names)[:1]
    assert rank("m5.xlrge", names)[0] == "m5.xlarge"
    assert rank("zzzz", names) == []


def test_resolve_exact_and_case_insensitive() -> None:
    hint = "hint"
    assert resolve("NVIDIA H100 SXM 80GB", GPUS, what="GPU", hint=hint) == GPUS[0]
    assert resolve("nvidia h100 sxm 80gb", GPUS, what="GPU", hint=hint) == GPUS[0]


def test_resolve_unique_partial_name() -> None:
    assert resolve("h100 sxm", GPUS, what="GPU", hint="") == "NVIDIA H100 SXM 80GB"
    assert resolve("a100", GPUS, what="GPU", hint="") == "NVIDIA A100 SXM4 80GB"


def test_resolve_refuses_ambiguous_names() -> None:
    with pytest.raises(InputError) as exc:
        resolve("h100", GPUS, what="GPU", hint="Call search_catalog.")
    message = str(exc.value)
    assert message.startswith("GPU 'h100' matches 2 names")
    assert "NVIDIA H100 SXM 80GB" in message
    assert "NVIDIA H100 PCIe 80GB" in message
    assert "Call search_catalog." in message


def test_whole_words_beat_substrings() -> None:
    names = ["Intel Xeon Gold 6134", "Intel Xeon Gold 6134M"]
    assert resolve("xeon gold 6134", names, what="CPU", hint="") == names[0]


def test_resolve_unknown_name_suggests_close_matches() -> None:
    with pytest.raises(InputError, match="Close matches: NVIDIA H100 SXM 80GB"):
        resolve("NVIDIA H100 SMX 80GB", GPUS, what="GPU", hint="")


async def test_lists_come_from_the_api(catalog: Catalog) -> None:
    assert len(await catalog.gpu_names()) == 40
    assert len(await catalog.cpu_names()) > 1000
    assert await catalog.providers() == ["aws", "azure", "gcp", "ovhcloud", "scaleway"]
    assert "m5.xlarge" in await catalog.instances("AWS")
    assert ("aws", "eu-west-3") in await catalog.regions("aws")
    assert "platfom_gpucompute_high" in await catalog.server_archetypes()
    assert "smart_watch" in await catalog.device_archetypes("iot_device")
    assert (await catalog.countries())["France"] == "FRA"
    criteria = await catalog.criteria()
    assert criteria["gwp"].unit == "kgCO2eq"
    assert criteria["ctuh_c"].method == "PEF"


async def test_search(catalog: Catalog) -> None:
    hits = await catalog.search("gpu", "h100")
    assert hits.total == 3
    assert all("H100" in name for name in hits.names)

    hits = await catalog.search("cloud_instance", "m5.xl", provider="aws", limit=3)
    assert hits.names[0] == "m5.xlarge"
    assert len(hits.names) == 3

    hits = await catalog.search("country", "germ")
    assert hits.names == ["Germany (DEU)"]

    hits = await catalog.search("cloud_region", "eu-west", provider="aws")
    assert "eu-west-3" in hits.names

    everything = await catalog.search("cloud_provider")
    assert everything.total == 5


@pytest.mark.parametrize(
    ("kind", "kwargs", "message"),
    [
        ("cloud_instance", {}, "needs a provider"),
        ("device_archetype", {}, "needs a device_type"),
        ("cloud_instance", {"provider": "ibm"}, "Unknown cloud provider"),
    ],
)
async def test_search_input_errors(
    catalog: Catalog, kind: str, kwargs: dict[str, str], message: str
) -> None:
    with pytest.raises(InputError, match=message):
        await catalog.search(kind, None, **kwargs)  # type: ignore[arg-type]


async def test_resolve_names(catalog: Catalog) -> None:
    assert await catalog.resolve_gpu("h100 sxm") == "NVIDIA H100 SXM 80GB"
    assert await catalog.resolve_cpu("xeon gold 6134") == "Intel Xeon Gold 6134"
    assert await catalog.resolve_instance("aws", "M5.XLARGE") == "m5.xlarge"
    assert await catalog.resolve_region("aws", "eu-west-3") == "eu-west-3"
    assert (
        await catalog.resolve_server_archetype("platfom_gpucompute_high")
        == "platfom_gpucompute_high"
    )
    assert await catalog.resolve_device_archetype("iot_device", "smart watch") == (
        "smart_watch"
    )


async def test_unknown_region_is_rejected(catalog: Catalog) -> None:
    with pytest.raises(InputError, match="Unknown aws region 'mars-1'"):
        await catalog.resolve_region("aws", "mars-1")


@pytest.mark.parametrize(
    ("text", "code", "name"),
    [
        ("DEU", "DEU", "Germany"),
        ("fra", "FRA", "France"),
        ("Germany", "DEU", "Germany"),
        ("united states", "USA", "United States"),
        ("US", "USA", "United States"),
        ("WOR", "WOR", "World"),
        ("Europe", "EEE", "Europe"),
    ],
)
async def test_resolve_location(
    catalog: Catalog, text: str, code: str, name: str
) -> None:
    location = await catalog.resolve_location(text)
    assert (location.code, location.name) == (code, name)


async def test_unknown_location_is_rejected(catalog: Catalog) -> None:
    with pytest.raises(InputError, match="Unknown location 'XXX'"):
        await catalog.resolve_location("XXX")


async def test_validate_criteria(catalog: Catalog) -> None:
    assert await catalog.validate_criteria(["GWP", "pe", "gwp"]) == ["gwp", "pe"]
    with pytest.raises(InputError, match="'all' is not supported"):
        await catalog.validate_criteria(["all"])
    with pytest.raises(InputError, match="Unknown impact criterion 'bogus'"):
        await catalog.validate_criteria(["bogus"])
    with pytest.raises(InputError, match="At least one"):
        await catalog.validate_criteria([])


def test_substring_only_matches_are_suggested_not_accepted() -> None:
    names = ["Nigeria", "France"]
    with pytest.raises(
        InputError, match=r"Unknown country 'Niger'.*Close matches: Nigeria"
    ):
        resolve("Niger", names, what="country", hint="")
    with pytest.raises(InputError, match=r"Unknown instance 't3\.large'"):
        resolve("t3.large", ["t3a.large", "m5.large"], what="instance", hint="")


def test_punctuation_only_input_is_rejected() -> None:
    with pytest.raises(InputError, match="'!!!' is not a valid GPU"):
        resolve("!!!", GPUS, what="GPU", hint="")


async def test_missing_country_is_not_swapped_for_a_similar_one(
    catalog: Catalog,
) -> None:
    with pytest.raises(InputError, match="Unknown location 'Niger'"):
        await catalog.resolve_location("Niger")


async def test_location_records_how_it_was_matched(catalog: Catalog) -> None:
    assert (await catalog.resolve_location("FRA")).exact is True
    location = await catalog.resolve_location("united states")
    assert location.exact is True
    assert location.requested == "united states"
