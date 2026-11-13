"""A small in-memory cache with expiry and a size bound (least recently used)."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Generic, TypeVar

V = TypeVar("V")

_MISSING = object()


class TTLCache(Generic[V]):
    """Entries expire ``ttl`` seconds after they are set. ``ttl <= 0`` disables it."""

    def __init__(
        self,
        ttl: float,
        maxsize: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl = ttl
        self.maxsize = maxsize
        self._clock = clock
        self._data: OrderedDict[Hashable, tuple[float, V]] = OrderedDict()

    @property
    def enabled(self) -> bool:
        return self.ttl > 0 and self.maxsize > 0

    def get(self, key: Hashable) -> tuple[bool, V | None]:
        """Return ``(True, value)`` on a hit and ``(False, None)`` on a miss."""
        if not self.enabled:
            return False, None
        entry = self._data.get(key, _MISSING)
        if entry is _MISSING:
            return False, None
        assert isinstance(entry, tuple)
        expires, value = entry
        if expires <= self._clock():
            del self._data[key]
            return False, None
        self._data.move_to_end(key)
        return True, value

    def set(self, key: Hashable, value: V) -> None:
        if not self.enabled:
            return
        self._data[key] = (self._clock() + self.ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)
