from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any


class MetricsStore:
    def __init__(self, maxlen: int = 2000) -> None:
        self._items: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = asyncio.Lock()

    async def record(self, item: dict[str, Any]) -> None:
        payload = dict(item)
        payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        async with self._lock:
            self._items.appendleft(payload)

    async def latest(self, limit: int = 200) -> list[dict[str, Any]]:
        async with self._lock:
            return list(self._items)[: max(1, min(limit, 1000))]


metrics_store = MetricsStore()
