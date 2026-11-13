"""Settings read from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_URL = "https://api.boavizta.org"
DEFAULT_TIMEOUT = 20.0
DEFAULT_CRITERIA = ("gwp", "adp", "pe")
DEFAULT_CACHE_TTL = 86400.0


class ConfigError(ValueError):
    """An environment variable has an invalid value."""


@dataclass(frozen=True)
class Settings:
    base_url: str = DEFAULT_URL
    timeout: float = DEFAULT_TIMEOUT
    default_criteria: tuple[str, ...] = DEFAULT_CRITERIA
    cache_ttl: float = DEFAULT_CACHE_TTL

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        return cls(
            base_url=_base_url(env.get("BOAVIZTAPI_URL", "")),
            timeout=_number(env, "BOAVIZTAPI_TIMEOUT", DEFAULT_TIMEOUT, minimum=0.0),
            default_criteria=_criteria(env.get("BOAVIZTAPI_DEFAULT_CRITERIA", "")),
            cache_ttl=_number(
                env,
                "BOAVIZTAPI_CACHE_TTL",
                DEFAULT_CACHE_TTL,
                minimum=0.0,
                strict=False,
            ),
        )


def _base_url(raw: str) -> str:
    value = raw.strip()
    if not value:
        return DEFAULT_URL
    if not value.startswith(("http://", "https://")):
        raise ConfigError(
            f"BOAVIZTAPI_URL must start with http:// or https://, got {value!r}"
        )
    return value.rstrip("/")


def _number(
    env: Mapping[str, str],
    name: str,
    default: float,
    *,
    minimum: float,
    strict: bool = True,
) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None
    too_small = value <= minimum if strict else value < minimum
    if too_small:
        bound = "greater than" if strict else "at least"
        raise ConfigError(f"{name} must be {bound} {minimum:g}, got {raw!r}")
    return value


def _criteria(raw: str) -> tuple[str, ...]:
    items = tuple(dict.fromkeys(p.strip() for p in raw.split(",") if p.strip()))
    return items or DEFAULT_CRITERIA
