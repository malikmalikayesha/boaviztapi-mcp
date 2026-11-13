# boaviztapi-mcp

[![CI](https://github.com/malikmalikayesha/boaviztapi-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/malikmalikayesha/boaviztapi-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/boaviztapi-mcp)](https://pypi.org/project/boaviztapi-mcp/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

<!-- mcp-name: io.github.malikmalikayesha/boaviztapi-mcp -->

An [MCP](https://modelcontextprotocol.io) server that lets AI assistants answer questions about the environmental footprint of IT hardware: cloud instances, servers, GPUs and other components, and end-user devices. It asks [BoaviztAPI](https://github.com/Boavizta/boaviztapi) and reports the answer with units, uncertainty ranges and caveats.

> Unofficial community project. Every number comes from BoaviztAPI, built by [Boavizta](https://boavizta.org). See their [methodology documentation](https://doc.api.boavizta.org) for how impacts are computed.

## Quick start

You need [uv](https://docs.astral.sh/uv/). The server talks to the public BoaviztAPI instance by default.

**Claude Desktop, Cursor and other clients with an `mcpServers` config:**

```json
{
  "mcpServers": {
    "boaviztapi": {
      "command": "uvx",
      "args": ["boaviztapi-mcp"]
    }
  }
}
```

**Claude Code:**

```bash
claude mcp add boaviztapi -- uvx boaviztapi-mcp
```

**Docker:**

```bash
docker build -t boaviztapi-mcp .
docker run -i --rm boaviztapi-mcp
```

**Try it without a client** using the [MCP Inspector](https://github.com/modelcontextprotocol/inspector):

```bash
npx @modelcontextprotocol/inspector uvx boaviztapi-mcp
```

## What you can ask

- "What is the footprint of 4 H100 SXM GPUs running for a year in Germany?"
- "Compare an AWS m5.xlarge in France and in the US over a month."
- "What is the embedded carbon of a typical laptop?"
- "Which is greener in eu-west-3 at 50% load: m5.xlarge or c5.2xlarge?"
- "What would a server with 2x Xeon Gold 6134 and 384 GB RAM emit over 5 years in France?"
- "What does `adp` mean and what unit is it in?"

A real answer for the first question, as the `summary` of `estimate_component`:

```
4x NVIDIA H100 SXM 80GB, over 8760 h (1 year), in Germany (DEU)
Embedded = the share of manufacturing allocated to 8760 h of a 26280 h lifetime.
gwp, Total climate change (kgCO2eq):
  embedded: 766.8
  use: 7100 (range 1035 to 10350)
  total: 7867 (range 1802 to 11120)
adp, Use of minerals and fossil ressources (kgSbeq):
  embedded: 0.007776
  use: 0.0015 (range 0.0002155 to 0.002155)
  total: 0.009276 (range 0.007992 to 0.009931)
pe, Consumption of primary energy (MJ):
  embedded: 10550
  use: 270000 (range 39880 to 398800)
  total: 280600 (range 50430 to 409400)
Assumptions: units 4, TDP 700 W, average power 479.5 W, load 65 %, use time ratio 1, lifetime 26280 hours, grid carbon intensity 0.422 kg CO2eq/kWh.
Note: GPU only; the host server is not included. Use estimate_server with a gpu block for a whole system.
Source: BoaviztAPI 2.6.0 at https://api.boavizta.org
```

## Tools

All tools are read-only. Each returns structured content plus a plain-text `summary`.

| Tool | What it does | Key inputs |
|---|---|---|
| `list_impact_criteria` | Explains impact criteria codes and units | `query` |
| `search_catalog` | Finds exact names before estimating | `kind` (cloud_provider, cloud_instance, cloud_region, server_archetype, device_archetype, gpu, cpu, country), `query`, `provider`, `device_type` |
| `describe_catalog_item` | Shows what an instance, archetype, GPU or CPU contains | `kind`, `name` |
| `estimate_cloud_instance` | Footprint of one cloud VM | `provider`, `instance_type`, `region` or `usage_location`, `load_percent` |
| `estimate_server` | Footprint of an on-premise server, optionally with GPUs | `archetype`, `cpu`, `ram`, `disks`, `gpu`, usage fields |
| `estimate_component` | Footprint of one GPU, CPU, RAM module, SSD or HDD | `component`, `name`, `units`, `capacity_gb` |
| `estimate_device` | Footprint of a laptop, phone, monitor, IoT device and 9 other types | `device_type`, `archetype` |
| `compare_estimates` | Ranks 2 to 5 options over the same period | `items`, `duration_hours` |

The estimate tools also take `duration_hours`, `usage_location`, `criteria` (default `gwp`, `adp`, `pe`) and `detail` (`summary` or `breakdown`).

## Reading the results

- **Embedded vs use.** Embedded is manufacturing (and transport where modelled); use is the electricity consumed. They are always reported separately, with a total only when both are numbers.
- **Period.** Without `duration_hours`, figures cover the whole hardware lifetime. With it, embedded is the share of manufacturing for that period and use is the energy for that period. If the period is longer than the lifetime, BoaviztAPI counts manufacturing once; the result says so.
- **Ranges.** `(range a to b)` is BoaviztAPI's min and max. When two options' ranges overlap, `compare_estimates` says the ranking is not certain.
- **Location.** Use-phase impacts depend on the electricity mix. Without a location BoaviztAPI uses a European default with a wide range, and the result suggests passing a country.
- **"not available from BoaviztAPI for this item"** means there is no data for that criterion and phase. It is never a zero.
- **Warnings** such as "End of life is not included in the calculation" stay next to the phase they belong to.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `BOAVIZTAPI_URL` | `https://api.boavizta.org` | BoaviztAPI base URL |
| `BOAVIZTAPI_TIMEOUT` | `20` | Seconds per request |
| `BOAVIZTAPI_DEFAULT_CRITERIA` | `gwp,adp,pe` | Criteria used when a call names none |
| `BOAVIZTAPI_CACHE_TTL` | `86400` | Seconds to cache list and lookup responses; `0` disables caching |

### Self-host BoaviztAPI for regular use

The public instance is a demo. For anything beyond occasional questions, run your own:

```bash
docker run -p 5000:5000 ghcr.io/boavizta/boaviztapi:latest
```

then set `BOAVIZTAPI_URL=http://localhost:5000` in the server's environment. The server is polite either way: it identifies itself in the `User-Agent`, caches lists and recent estimates, sends at most four requests at a time, and retries only transient failures.

## Upstream behaviour this server works around

Found while building this against BoaviztAPI 2.6.0. Each one has a live test that will start failing (on purpose) when upstream changes it.

- Unknown criteria and `criteria=all` return HTTP 500, so criteria are checked locally and `all` is refused.
- Unknown locations and cloud regions are accepted without an error and give generic results, so both are checked against the API's own lists.
- `name_to_gpu` silently picks one GPU for an ambiguous name and returns 200 with a plain string when nothing matches, so names are resolved here and ambiguous ones are refused.
- An `iot_device` without an archetype reports 0 for manufacturing, so an archetype is required.
- The GPU endpoint returns 500 for some criteria on the public instance (fixed upstream in Boavizta/boaviztapi#621, not yet deployed). A failing multi-criteria request is retried one criterion at a time, and only the failing criteria are marked as errors.

## Development

```bash
uv sync
uv run pytest                 # unit and tool tests, replaying recorded responses
uv run ruff check . && uv run ruff format --check . && uv run pyright
```

- **Recorded responses** live in `tests/fixtures/`. Re-record them after a BoaviztAPI release with `uv run python scripts/record_fixtures.py --clean` and review the diff.
- **Summaries** are checked against `tests/golden/`; regenerate them with `UPDATE_GOLDEN=1 uv run pytest tests/unit/test_formatting.py`.
- **Live tests** run against a real instance: start the Docker image above, then `BOAVIZTAPI_URL=http://localhost:5000 uv run pytest -m live -rxX`.

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. BoaviztAPI itself is AGPL-3.0 and is not bundled; see [NOTICE](NOTICE).
