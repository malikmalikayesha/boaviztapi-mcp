# Contributing

Thanks for helping. Small, focused pull requests are the easiest to review.

## Setup

```bash
uv sync
uv run pytest
```

Before opening a pull request, these must pass:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

## Conventions

- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat(tools): ...`, `fix(catalog): ...`).
- Only `src/boaviztapi_mcp/server.py` imports the MCP SDK. Everything else is plain async Python and is tested without it.
- The server never computes impacts itself. It only sums embedded and use into a total. If a number looks wrong, check it against BoaviztAPI directly and report it [upstream](https://github.com/Boavizta/boaviztapi/issues).

## Tests and fixtures

- Tests replay recorded BoaviztAPI responses from `tests/fixtures/`. To cover a new request, add a scenario to `tests/scenarios.py` and record it:

  ```bash
  uv run python scripts/record_fixtures.py
  ```

  Use `--base-url http://localhost:5000` to record from a local instance.
- Summary text is compared with `tests/golden/`. After an intended change, regenerate with `UPDATE_GOLDEN=1 uv run pytest tests/unit/test_formatting.py` and review the diff.
- `docs/tools.md` is generated from the tool schemas. After changing a tool, its parameters or their descriptions, run `uv run python scripts/gen_tool_docs.py`; `tests/test_docs.py` fails until you do.
- Live tests (`-m live`) run against a real instance:

  ```bash
  docker run -p 5000:5000 ghcr.io/boavizta/boaviztapi:latest
  BOAVIZTAPI_URL=http://localhost:5000 uv run pytest -m live -rxX
  ```

  Known upstream quirks are strict `xfail` tests. If one starts passing, upstream changed: review the matching workaround and remove it if it is no longer needed.

## Releasing

One-time setup (already done once the first release is out):

- On PyPI, add a trusted publisher for the project `boaviztapi-mcp`: owner `malikmalikayesha`, repository `boaviztapi-mcp`, workflow `release.yml`, environment `pypi`.
- In the repository settings, create the `pypi` environment.
- The MCP Registry needs no secret: `release.yml` logs in with GitHub OIDC, and the registry checks the `mcp-name` line in the README on PyPI.
- Glama lists the repository from `glama.json`; a maintainer claims it once by signing in to glama.ai with GitHub.

Each release:

1. Update the version in `src/boaviztapi_mcp/__init__.py` and `server.json` (both `version` fields), and move the `Unreleased` notes in `CHANGELOG.md` under the new version.
2. Merge, then tag `vX.Y.Z` on `main` and push the tag. The release workflow publishes to PyPI, the MCP Registry and GitHub Releases.
