# Tool reference

Generated from the server's tool schemas by `scripts/gen_tool_docs.py`; do not
edit by hand. Every tool is read-only, idempotent and calls BoaviztAPI over the
network. Every tool returns structured content and a plain-text `summary`.

## Contents

- [`list_impact_criteria`](#list_impact_criteria): List impact criteria
- [`search_catalog`](#search_catalog): Search the BoaviztAPI catalog
- [`describe_catalog_item`](#describe_catalog_item): Describe a catalog item
- [`estimate_cloud_instance`](#estimate_cloud_instance): Estimate a cloud instance
- [`estimate_server`](#estimate_server): Estimate a server
- [`estimate_component`](#estimate_component): Estimate a component
- [`estimate_device`](#estimate_device): Estimate an end-user device
- [`compare_estimates`](#compare_estimates): Compare estimates

## `list_impact_criteria`

**List impact criteria**

List BoaviztAPI impact criteria with their codes, units and meaning.

Use it to explain a code such as gwp (climate change, kgCO2eq), adp (abiotic resources, kgSbeq) or pe (primary energy, MJ), or to pick criteria for the estimate tools.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | no |  | Optional filter on code or description, e.g. 'water'. |

Returns `CriteriaList`.

## `search_catalog`

**Search the BoaviztAPI catalog**

Find the exact names BoaviztAPI knows before estimating.

Kinds: cloud_provider, cloud_instance, cloud_region, server_archetype, device_archetype, gpu, cpu and country. Results are exact upstream strings (including upstream typos such as 'platfom_gpucompute_high').

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `kind` | one of `cloud_provider`, `cloud_instance`, `cloud_region`, `server_archetype`, `device_archetype`, `gpu`, `cpu`, `country` | yes |  | What to search. |
| `query` | string | no |  | Words to match, e.g. 'h100', 'm5.x', 'germ'. |
| `provider` | string | no |  | Cloud provider; required for cloud_instance, optional for cloud_region. |
| `device_type` | one of `laptop`, `desktop`, `smartphone`, `tablet`, `television`, `box`, `vr_headset`, `monitor`, `usb_stick`, `external_ssd`, `external_hdd`, `vr_controller`, `iot_device` | no |  | Required for device_archetype. |
| `limit` | integer (>= 1, <= 100) | no | `20` | Maximum names to return. |

Returns `SearchResult`.

## `describe_catalog_item`

**Describe a catalog item**

Show what a named item contains: an instance's vCPUs and memory, a server or device archetype's default parts and usage, or a GPU's or CPU's specs.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `kind` | one of `cloud_instance`, `server_archetype`, `device_archetype`, `gpu`, `cpu` | yes |  | What kind of item. |
| `name` | string | yes |  | Name as found with search_catalog. |
| `provider` | string | no |  | Required for cloud_instance. |
| `device_type` | one of `laptop`, `desktop`, `smartphone`, `tablet`, `television`, `box`, `vr_headset`, `monitor`, `usb_stick`, `external_ssd`, `external_hdd`, `vr_controller`, `iot_device` | no |  | Required for device_archetype. |

Returns `CatalogItem`.

## `estimate_cloud_instance`

**Estimate a cloud instance**

Estimate the footprint of one cloud instance (its share of the host).

Returns embedded and use impacts per criterion with units, ranges and warnings. Use search_catalog(kind='cloud_instance', provider=...) if unsure of the instance name.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `provider` | string | yes |  | Cloud provider, e.g. 'aws'. |
| `instance_type` | string | yes |  | Instance type, e.g. 'm5.xlarge'. |
| `region` | string | no |  | Provider region such as 'eu-west-3'; exclusive with usage_location. |
| `usage_location` | string | no |  | Where the electricity comes from: country name or 3-letter code ('Germany', 'DEU'), 'WOR' for world or 'EEE' for Europe. |
| `load_percent` | number (>= 0, <= 100) | no |  | Average CPU load in percent. |
| `duration_hours` | number (> 0) | no |  | Period assessed in hours (8760 = 1 year, 730 = 1 month). Omit for the whole hardware lifetime. |
| `criteria` | list of string | no |  | Impact criteria codes; default gwp, adp, pe. See list_impact_criteria. 'all' is not accepted. |
| `detail` | one of `summary`, `breakdown` | no | `summary` | 'breakdown' adds per-component impacts and all assumptions. |

Returns `EstimateResult`.

## `estimate_server`

**Estimate a server**

Estimate the footprint of an on-premise server, optionally with GPUs.

Parts not given come from the archetype; the result says which. The default lifetime is 4 years (35040 h). A period longer than the lifetime counts manufacturing once.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `archetype` | string | no |  | Server archetype for anything not given (default 'platform_compute_medium'); see search_catalog. |
| `server_type` | one of `rack`, `blade` | no |  | Form factor; defaults to the archetype's (rack). |
| `cpu` | [`CpuSpec`](#cpuspec) | no |  | CPUs, e.g. {name: 'Xeon Gold 6134', units: 2}. |
| `ram` | list of [`RamSpec`](#ramspec) | no |  | RAM modules, e.g. [{units: 12, capacity_gb: 32}]. |
| `disks` | list of [`DiskSpec`](#diskspec) | no |  | Disks, e.g. [{type: 'ssd', units: 2, capacity_gb: 960}]. |
| `gpu` | [`GpuSpec`](#gpuspec) | no |  | GPUs, e.g. {name: 'A100 SXM4 80GB', units: 8}. |
| `avg_power_w` | number (> 0) | no |  | Average power in watts. |
| `load_percent` | number (>= 0, <= 100) | no |  | Average CPU load in percent. |
| `gpu_load_percent` | number (>= 0, <= 100) | no |  | Average GPU load in percent. |
| `use_time_ratio` | number (>= 0, <= 1) | no |  | Share of time the device is in use, 0 to 1. |
| `lifetime_hours` | number (> 0) | no |  | Hardware lifetime in hours. |
| `usage_location` | string | no |  | Where the electricity comes from: country name or 3-letter code ('Germany', 'DEU'), 'WOR' for world or 'EEE' for Europe. |
| `duration_hours` | number (> 0) | no |  | Period assessed in hours (8760 = 1 year, 730 = 1 month). Omit for the whole hardware lifetime. |
| `criteria` | list of string | no |  | Impact criteria codes; default gwp, adp, pe. See list_impact_criteria. 'all' is not accepted. |
| `detail` | one of `summary`, `breakdown` | no | `summary` | 'breakdown' adds per-component impacts and all assumptions. |

Returns `EstimateResult`.

## `estimate_component`

**Estimate a component**

Estimate the footprint of a single component: gpu, cpu, ram, ssd or hdd.

A GPU alone excludes its host server; use estimate_server with a gpu block for a whole system.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `component` | one of `gpu`, `cpu`, `ram`, `ssd`, `hdd` | yes |  | Component type. |
| `name` | string | no |  | Model name for gpu or cpu, e.g. 'H100 SXM'. |
| `units` | integer (>= 1) | no | `1` | How many. |
| `capacity_gb` | integer (> 0) | no |  | Capacity in GB (ram, ssd, hdd). |
| `tdp_w` | number (> 0) | no |  | TDP in watts (gpu, cpu). |
| `avg_power_w` | number (> 0) | no |  | Average power in watts. |
| `load_percent` | number (>= 0, <= 100) | no |  | Average CPU load in percent. |
| `lifetime_hours` | number (> 0) | no |  | Hardware lifetime in hours. |
| `usage_location` | string | no |  | Where the electricity comes from: country name or 3-letter code ('Germany', 'DEU'), 'WOR' for world or 'EEE' for Europe. |
| `duration_hours` | number (> 0) | no |  | Period assessed in hours (8760 = 1 year, 730 = 1 month). Omit for the whole hardware lifetime. |
| `criteria` | list of string | no |  | Impact criteria codes; default gwp, adp, pe. See list_impact_criteria. 'all' is not accepted. |
| `detail` | one of `summary`, `breakdown` | no | `summary` | 'breakdown' adds per-component impacts and all assumptions. |

Returns `EstimateResult`.

## `estimate_device`

**Estimate an end-user device**

Estimate the footprint of an end-user device: laptop, desktop, smartphone, tablet, television, box, VR headset or controller, monitor, USB stick, external SSD or HDD, or an IoT device.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `device_type` | one of `laptop`, `desktop`, `smartphone`, `tablet`, `television`, `box`, `vr_headset`, `monitor`, `usb_stick`, `external_ssd`, `external_hdd`, `vr_controller`, `iot_device` | yes |  | Kind of device. |
| `archetype` | string | no |  | Device archetype, e.g. 'laptop-pro'; required for iot_device. See search_catalog(kind='device_archetype'). |
| `avg_power_w` | number (> 0) | no |  | Average power in watts. |
| `use_time_ratio` | number (>= 0, <= 1) | no |  | Share of time the device is in use, 0 to 1. |
| `lifetime_hours` | number (> 0) | no |  | Hardware lifetime in hours. |
| `usage_location` | string | no |  | Where the electricity comes from: country name or 3-letter code ('Germany', 'DEU'), 'WOR' for world or 'EEE' for Europe. |
| `duration_hours` | number (> 0) | no |  | Period assessed in hours (8760 = 1 year, 730 = 1 month). Omit for the whole hardware lifetime. |
| `criteria` | list of string | no |  | Impact criteria codes; default gwp, adp, pe. See list_impact_criteria. 'all' is not accepted. |
| `detail` | one of `summary`, `breakdown` | no | `summary` | 'breakdown' adds per-component impacts and all assumptions. |

Returns `EstimateResult`.

## `compare_estimates`

**Compare estimates**

Compare 2 to 5 options (cloud instances, servers, components or devices) over the same period and rank them per criterion, saying when their uncertainty ranges overlap.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `items` | list of [`CompareItemInput`](#compareiteminput) (at least 2 items, at most 5 items) | yes |  | 2 to 5 options. |
| `duration_hours` | number (> 0) | yes |  | Common period in hours for every option (8760 = 1 year), so options with different lifetimes compare fairly. |
| `criteria` | list of string | no |  | Impact criteria codes; default gwp, adp, pe. See list_impact_criteria. 'all' is not accepted. |

Returns `ComparisonResult`.

## Input types

### `CompareItemInput`

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `label` | string | yes |  | Short unique name for this option. |
| `kind` | one of `cloud_instance`, `server`, `component`, `device` | yes |  | Which estimate tool's inputs params holds. |
| `params` | object | yes |  | The inputs of the matching estimate tool, without duration_hours, criteria and detail. cloud_instance: provider, instance_type, region or usage_location, load_percent. server: archetype, server_type, cpu, ram, disks, gpu, avg_power_w, load_percent, gpu_load_percent, use_time_ratio, lifetime_hours, usage_location. component: component, name, units, capacity_gb, tdp_w, avg_power_w, load_percent, lifetime_hours, usage_location. device: device_type, archetype, avg_power_w, use_time_ratio, lifetime_hours, usage_location. |

### `CpuSpec`

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | no |  | CPU model name. |
| `units` | integer (>= 1) | no |  | Number of CPUs. |
| `core_units` | integer (>= 1) | no |  | Cores per CPU. |
| `tdp_w` | number (> 0) | no |  | TDP in watts. |

### `DiskSpec`

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `type` | one of `ssd`, `hdd` | yes |  | Disk technology. |
| `units` | integer (>= 1) | no | `1` | Number of disks. |
| `capacity_gb` | integer (> 0) | no |  | Capacity of one disk in GB. |

### `GpuSpec`

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | no |  | GPU model name. |
| `units` | integer (>= 1) | no | `1` | Number of GPUs. |

### `RamSpec`

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `units` | integer (>= 1) | no | `1` | Number of modules. |
| `capacity_gb` | integer (> 0) | yes |  | Capacity of one module in GB. |
