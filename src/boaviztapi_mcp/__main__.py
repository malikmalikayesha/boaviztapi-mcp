"""Command-line entry point: ``boaviztapi-mcp`` or ``python -m boaviztapi_mcp``."""

from __future__ import annotations

import argparse
import sys

from boaviztapi_mcp import __version__


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="boaviztapi-mcp",
        description="MCP server for BoaviztAPI (stdio transport).",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.parse_args(argv)
    print("boaviztapi-mcp: the server is not implemented yet", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
