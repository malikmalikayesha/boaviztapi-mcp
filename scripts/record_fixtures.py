"""Record the BoaviztAPI responses that the test suite replays.

Usage:
    uv run python scripts/record_fixtures.py [--base-url URL] [--clean]

It runs every scenario in tests/scenarios.py through the real code paths with a
recording transport, so the fixtures contain exactly the requests the code sends.
Re-run it after a BoaviztAPI release and review the diff.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.replay import FIXTURES, RecordingTransport  # noqa: E402
from tests.scenarios import SCENARIOS  # noqa: E402

from boaviztapi_mcp.client import BoaviztaClient  # noqa: E402
from boaviztapi_mcp.config import Settings  # noqa: E402


async def record(base_url: str, clean: bool) -> None:
    if clean:
        for path in FIXTURES.glob("*.json"):
            path.unlink()
    transport = RecordingTransport(FIXTURES, httpx2.AsyncHTTPTransport())
    client = BoaviztaClient(
        Settings(base_url=base_url, timeout=60, cache_ttl=0), transport=transport
    )
    try:
        version = await client.version()
        for name, scenario in SCENARIOS.items():
            print(f"recording {name}", file=sys.stderr)
            await scenario(client)
    finally:
        await client.aclose()
    meta = {"base_url": base_url, "api_version": version}
    (FIXTURES / "_meta.json.txt").write_text(json.dumps(meta, indent=1) + "\n")
    unique = {path.name for path in transport.written}
    print(f"wrote {len(unique)} fixtures from {base_url} ({version})", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record BoaviztAPI fixtures for the test suite."
    )
    parser.add_argument("--base-url", default="https://api.boavizta.org")
    parser.add_argument(
        "--clean", action="store_true", help="delete existing fixtures first"
    )
    args = parser.parse_args()
    asyncio.run(record(args.base_url.rstrip("/"), args.clean))


if __name__ == "__main__":
    main()
