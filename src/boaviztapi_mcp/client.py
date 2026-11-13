"""Async HTTP client for BoaviztAPI.

It is deliberately polite to the public demo instance: it sends an identifying
User-Agent, caches list and lookup endpoints, caches estimates for a short time,
runs at most four requests at once and retries only transient failures.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

import httpx2

from boaviztapi_mcp import __version__
from boaviztapi_mcp.cache import TTLCache
from boaviztapi_mcp.config import Settings
from boaviztapi_mcp.errors import (
    UnexpectedResponse,
    UpstreamError,
    UpstreamNotFound,
    UpstreamServerError,
    UpstreamUnavailable,
    UpstreamValidationError,
)

USER_AGENT = f"boaviztapi-mcp/{__version__} (+https://github.com/malikmalikayesha/boaviztapi-mcp)"
MAX_CONCURRENCY = 4
RETRY_STATUSES = frozenset({502, 503, 504})
ATTEMPTS = 2
ESTIMATE_CACHE_TTL = 3600.0
ESTIMATE_CACHE_SIZE = 128
LOOKUP_CACHE_SIZE = 256

Params = Sequence[tuple[str, str]]


class BoaviztaClient:
    """Talks to one BoaviztAPI instance. Create one per server and reuse it."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
        retry_delay: float = 0.5,
    ) -> None:
        self.settings = settings
        self._transport = transport
        self._retry_delay = retry_delay
        self._http: httpx2.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        self._lookups: TTLCache[Any] = TTLCache(
            settings.cache_ttl, maxsize=LOOKUP_CACHE_SIZE
        )
        self._estimates: TTLCache[Any] = TTLCache(
            min(settings.cache_ttl, ESTIMATE_CACHE_TTL), maxsize=ESTIMATE_CACHE_SIZE
        )

    @property
    def base_url(self) -> str:
        return self.settings.base_url

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def get(self, path: str, params: Params = ()) -> Any:
        """GET a list or lookup endpoint. Results are cached for ``cache_ttl``."""
        key = ("GET", path, tuple(params))
        hit, value = self._lookups.get(key)
        if hit:
            return value
        value = await self._request("GET", path, params, None)
        self._lookups.set(key, value)
        return value

    async def post(self, path: str, params: Params, body: dict[str, Any]) -> Any:
        """POST an estimate. Identical requests are answered from a short cache."""
        key = ("POST", path, tuple(params), json.dumps(body, sort_keys=True))
        hit, value = self._estimates.get(key)
        if hit:
            return value
        value = await self._request("POST", path, params, body)
        self._estimates.set(key, value)
        return value

    async def version(self) -> str:
        value = await self.get("/v1/utils/version")
        return str(value)

    def _client(self) -> httpx2.AsyncClient:
        if self._http is None:
            self._http = httpx2.AsyncClient(
                base_url=self.base_url,
                timeout=self.settings.timeout,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                transport=self._transport,
            )
        return self._http

    async def _request(
        self, method: str, path: str, params: Params, body: dict[str, Any] | None
    ) -> Any:
        for attempt in range(1, ATTEMPTS + 1):
            last = attempt == ATTEMPTS
            try:
                async with self._semaphore:
                    response = await self._client().request(
                        method, path, params=list(params), json=body
                    )
            except httpx2.TimeoutException as exc:
                if not last:
                    await asyncio.sleep(self._retry_delay * attempt)
                    continue
                raise UpstreamUnavailable(
                    self.base_url, self.settings.timeout, "timed out"
                ) from exc
            except httpx2.TransportError as exc:
                if not last:
                    await asyncio.sleep(self._retry_delay * attempt)
                    continue
                raise UpstreamUnavailable(
                    self.base_url,
                    self.settings.timeout,
                    f"connection failed: {exc}" if str(exc) else "connection failed",
                ) from exc
            if response.status_code in RETRY_STATUSES and not last:
                await asyncio.sleep(self._retry_delay * attempt)
                continue
            return _decode(response)
        raise AssertionError("unreachable")  # pragma: no cover


def _decode(response: httpx2.Response) -> Any:
    status = response.status_code
    if 200 <= status < 300:
        try:
            return response.json()
        except ValueError:
            raise UnexpectedResponse(
                f"BoaviztAPI returned a body that is not JSON: {response.text[:200]!r}"
            ) from None
    if status == 404:
        raise UpstreamNotFound(_detail_text(response))
    if status == 422:
        raise UpstreamValidationError(_validation_problems(response))
    if status >= 500:
        raise UpstreamServerError(status, response.text)
    raise UpstreamError(f"BoaviztAPI returned HTTP {status}: {response.text[:200]}")


def _detail_text(response: httpx2.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or "not found"
    if isinstance(payload, dict) and isinstance(payload.get("detail"), str):
        return payload["detail"]
    return json.dumps(payload)[:200]


def _validation_problems(response: httpx2.Response) -> list[str]:
    try:
        payload = response.json()
    except ValueError:
        return [response.text.strip()[:200]]
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if not isinstance(detail, list):
        return [str(detail if detail is not None else payload)[:200]]
    problems = []
    for item in detail:
        if not isinstance(item, dict):
            problems.append(str(item))
            continue
        loc = [str(part) for part in item.get("loc", []) if part not in ("body",)]
        where = ".".join(loc)
        message = str(item.get("msg", "invalid value"))
        problems.append(f"{where}: {message}" if where else message)
    return problems
