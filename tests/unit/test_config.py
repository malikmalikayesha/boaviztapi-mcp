import pytest

from boaviztapi_mcp.config import (
    DEFAULT_CRITERIA,
    DEFAULT_URL,
    ConfigError,
    Settings,
)


def test_defaults_when_environment_is_empty() -> None:
    settings = Settings.from_env({})
    assert settings == Settings()
    assert settings.base_url == DEFAULT_URL
    assert settings.default_criteria == DEFAULT_CRITERIA


def test_reads_every_variable() -> None:
    settings = Settings.from_env(
        {
            "BOAVIZTAPI_URL": "http://localhost:5000/",
            "BOAVIZTAPI_TIMEOUT": "5",
            "BOAVIZTAPI_DEFAULT_CRITERIA": " gwp, pe ,gwp,",
            "BOAVIZTAPI_CACHE_TTL": "0",
        }
    )
    assert settings.base_url == "http://localhost:5000"
    assert settings.timeout == 5
    assert settings.default_criteria == ("gwp", "pe")
    assert settings.cache_ttl == 0


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("BOAVIZTAPI_URL", "api.boavizta.org", "must start with http"),
        ("BOAVIZTAPI_TIMEOUT", "soon", "must be a number"),
        ("BOAVIZTAPI_TIMEOUT", "0", "greater than 0"),
        ("BOAVIZTAPI_CACHE_TTL", "-1", "at least 0"),
    ],
)
def test_rejects_invalid_values(name: str, value: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        Settings.from_env({name: value})
