"""In-process event bus with monotonically increasing sequence numbers (`seq`)."""
from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger("bytedrop.events")

SyncSubscriber = Callable[[dict[str, Any]], None]
AsyncSubscriber = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class EventBus:
    """Single-source-of-truth event dispatcher assigning monotonic `seq` numbers to every event."""

    def __init__(self) -> None:
        self._seq: int = 0
        self._lock = threading.Lock()
        self._sync_subscribers: list[SyncSubscriber] = []
        self._async_subscribers: list[AsyncSubscriber] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def seq(self) -> int:
        with self._lock:
            return self._seq

    def set_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    def subscribe_sync(self, callback: SyncSubscriber) -> None:
        with self._lock:
            if callback not in self._sync_subscribers:
                self._sync_subscribers.append(callback)

    def subscribe_async(self, callback: AsyncSubscriber) -> None:
        with self._lock:
            if callback not in self._async_subscribers:
                self._async_subscribers.append(callback)

    def emit(self, event: dict[str, Any]) -> dict[str, Any]:
        """Assigns the next monotonic `seq` to event and dispatches to sync and async listeners."""
        with self._lock:
            self._seq += 1
            seq_val = self._seq
            sync_subs = list(self._sync_subscribers)
            async_subs = list(self._async_subscribers)

        payload = dict(event)
        payload["seq"] = seq_val

        for cb in sync_subs:
            try:
                cb(payload)
            except Exception as exc:
                logger.debug("Sync event subscriber error: %s", exc)

        loop = self._loop
        if async_subs and loop is not None and loop.is_running():
            for acb in async_subs:
                try:
                    asyncio.run_coroutine_threadsafe(acb(payload), loop)
                except Exception as exc:
                    logger.debug("Async event subscriber dispatch error: %s", exc)

        return payload
