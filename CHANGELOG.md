# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0]

### Added

- MCP server for BoaviztAPI over stdio with eight read-only tools:
  `list_impact_criteria`, `search_catalog`, `describe_catalog_item`,
  `estimate_cloud_instance`, `estimate_server`, `estimate_component`,
  `estimate_device` and `compare_estimates`.
- Structured results with a plain-text summary: units, min to max ranges, per-phase
  warnings, assumptions, notes and the BoaviztAPI version used.
- Local validation of criteria, locations, cloud regions and names before any call.
- Per-criterion fallback when BoaviztAPI returns 500 for a multi-criteria request.
- Caching, a concurrency limit and retries for transient failures.
- Configuration through `BOAVIZTAPI_URL`, `BOAVIZTAPI_TIMEOUT`,
  `BOAVIZTAPI_DEFAULT_CRITERIA` and `BOAVIZTAPI_CACHE_TTL`.
- Dockerfile, MCP Registry `server.json` and Glama `glama.json`.

[Unreleased]: https://github.com/malikmalikayesha/boaviztapi-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/malikmalikayesha/boaviztapi-mcp/releases/tag/v0.1.0
