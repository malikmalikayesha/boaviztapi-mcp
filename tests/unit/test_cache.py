from boaviztapi_mcp.cache import TTLCache


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_hit_until_expiry() -> None:
    clock = FakeClock()
    cache: TTLCache[str] = TTLCache(ttl=10, clock=clock)
    cache.set("k", "v")
    assert cache.get("k") == (True, "v")
    clock.now = 9.9
    assert cache.get("k") == (True, "v")
    clock.now = 10
    assert cache.get("k") == (False, None)
    assert len(cache) == 0


def test_none_is_a_valid_cached_value() -> None:
    cache: TTLCache[None] = TTLCache(ttl=10)
    cache.set("k", None)
    assert cache.get("k") == (True, None)


def test_evicts_least_recently_used() -> None:
    cache: TTLCache[int] = TTLCache(ttl=10, maxsize=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")
    cache.set("c", 3)
    assert cache.get("b") == (False, None)
    assert cache.get("a") == (True, 1)
    assert cache.get("c") == (True, 3)


def test_zero_ttl_disables_caching() -> None:
    cache: TTLCache[int] = TTLCache(ttl=0)
    cache.set("a", 1)
    assert cache.get("a") == (False, None)
    assert len(cache) == 0
