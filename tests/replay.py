"""Record BoaviztAPI responses to JSON files and replay them in tests.

A request is identified by its method, path, query parameters (order-insensitive)
and JSON body, so tests replay exactly what the code under test sends.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx2

FIXTURES = Path(__file__).parent / "fixtures"


def request_key(
    method: str, path: str, params: list[tuple[str, str]], body: Any
) -> dict[str, Any]:
    return {
        "method": method.upper(),
        "path": path,
        "params": sorted([list(p) for p in params]),
        "body": body,
    }


def key_of(request: httpx2.Request) -> dict[str, Any]:
    body = json.loads(request.content) if request.content else None
    return request_key(
        request.method, request.url.path, list(request.url.params.multi_items()), body
    )


def digest(key: dict[str, Any]) -> str:
    canonical = json.dumps(key, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def file_name(key: dict[str, Any]) -> str:
    slug = key["path"].strip("/").replace("/", "_") or "root"
    return f"{key['method'].lower()}_{slug}_{digest(key)}.json"


class RecordingTransport(httpx2.AsyncBaseTransport):
    """Forwards to a real transport and writes every exchange to ``directory``."""

    def __init__(self, directory: Path, inner: httpx2.AsyncBaseTransport) -> None:
        self.directory = directory
        self.inner = inner
        self.written: list[Path] = []

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        response = await self.inner.handle_async_request(request)
        content = await response.aread()
        key = key_of(request)
        try:
            body: Any = json.loads(content)
            kind = "json"
        except ValueError:
            body = content.decode(errors="replace")
            kind = "text"
        record = {"request": key, "status": response.status_code, kind: body}
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / file_name(key)
        path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n")
        self.written.append(path)
        return httpx2.Response(
            response.status_code, headers=response.headers, content=content
        )

    async def aclose(self) -> None:
        await self.inner.aclose()


class ReplayTransport(httpx2.AsyncBaseTransport):
    """Answers requests from recorded fixtures; unknown requests fail loudly."""

    def __init__(self, directory: Path = FIXTURES) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        for path in sorted(directory.glob("*.json")):
            record = json.loads(path.read_text())
            self.records[digest(record["request"])] = record
        self.seen: list[dict[str, Any]] = []

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        key = key_of(request)
        self.seen.append(key)
        record = self.records.get(digest(key))
        if record is None:
            raise AssertionError(
                "No recorded fixture for this request; run"
                f" scripts/record_fixtures.py. Request: {json.dumps(key)}"
            )
        if "json" in record:
            return httpx2.Response(record["status"], json=record["json"])
        return httpx2.Response(record["status"], text=record["text"])
