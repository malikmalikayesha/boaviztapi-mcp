# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1]

### Changed

- Every tool description now says when to use the tool and which tool to use
  instead, how its key inputs interact, and what a call does (one read-only,
  cached BoaviztAPI request; partial upstream failures still return the other
  criteria).

### Added

- Server icon (`assets/icon.svg`, `assets/icon.png`), advertised to MCP clients and
  in the MCP Registry entry.
- Glama score badge in the README and a Dependabot configuration.

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
- MCP specification 2026-07-28 (stateless, `server/discover`) with fallback to the
  2025-11-25 handshake; tool titles, a server description, and a cacheable tool list.
- Documentation: README with privacy, limitations and troubleshooting sections, a
  generated tool reference (`docs/tools.md`), contributing guide and security policy.

[Unreleased]: https://github.com/malikmalikayesha/boaviztapi-mcp/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/malikmalikayesha/boaviztapi-mcp/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/malikmalikayesha/boaviztapi-mcp/releases/tag/v0.1.0
