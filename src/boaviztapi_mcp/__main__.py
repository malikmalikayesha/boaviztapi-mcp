"""Command-line entry point: ``boaviztapi-mcp`` or ``python -m boaviztapi_mcp``."""

from __future__ import annotations

import argparse
import sys

from boaviztapi_mcp import __version__
from boaviztapi_mcp.config import ConfigError, Settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="boaviztapi-mcp",
        description="MCP server for BoaviztAPI over stdio. Configure it with the"
        " BOAVIZTAPI_URL, BOAVIZTAPI_TIMEOUT, BOAVIZTAPI_DEFAULT_CRITERIA and"
        " BOAVIZTAPI_CACHE_TTL environment variables.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.parse_args(argv)
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"boaviztapi-mcp: {exc}", file=sys.stderr)
        sys.exit(2)

    from boaviztapi_mcp.server import run

    run(settings)


if __name__ == "__main__":
    main()
