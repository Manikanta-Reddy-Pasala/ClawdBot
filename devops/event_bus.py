"""Simple async pub/sub for inter-module communication."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

Listener = Callable[..., Awaitable[None]]


class EventBus:
    def __init__(self):
        self._listeners: dict[str, list[Listener]] = defaultdict(list)

    def on(self, event: str, listener: Listener):
        self._listeners[event].append(listener)

    def off(self, event: str, listener: Listener):
        if event in self._listeners:
            self._listeners[event] = [l for l in self._listeners[event] if l != listener]

    async def emit(self, event: str, **kwargs):
        for listener in self._listeners.get(event, []):
            try:
                await listener(**kwargs)
            except Exception:
                logger.exception(f"Error in event listener for '{event}'")

    def emit_nowait(self, event: str, **kwargs):
        for listener in self._listeners.get(event, []):
            asyncio.create_task(self._safe_call(listener, event, **kwargs))

    async def _safe_call(self, listener: Listener, event: str, **kwargs):
        try:
            await listener(**kwargs)
        except Exception:
            logger.exception(f"Error in event listener for '{event}'")


event_bus = EventBus()
