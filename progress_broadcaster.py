"""SSE + WebSocket broadcast for real-time task progress."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Active SSE connections per task_id
_sse_queues: dict[int, list[asyncio.Queue]] = {}
# WebSocket connections
_ws_connections: list = []


def add_ws(ws):
    _ws_connections.append(ws)


def remove_ws(ws):
    if ws in _ws_connections:
        _ws_connections.remove(ws)


async def emit(event_type: str, task_id: int | None = None, **data):
    """Broadcast an event to SSE subscribers and WebSocket connections."""
    payload = {
        "type": event_type,
        "task_id": task_id,
        "timestamp": datetime.utcnow().isoformat(),
        **data,
    }

    # SSE: send to task-specific subscribers
    if task_id and task_id in _sse_queues:
        for queue in _sse_queues[task_id]:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    # WebSocket: broadcast to all
    msg = json.dumps(payload)
    dead = []
    for ws in _ws_connections:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        remove_ws(ws)


def subscribe_sse(task_id: int) -> asyncio.Queue:
    """Subscribe to SSE events for a specific task."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _sse_queues.setdefault(task_id, []).append(queue)
    return queue


def unsubscribe_sse(task_id: int, queue: asyncio.Queue):
    """Unsubscribe from SSE events."""
    if task_id in _sse_queues:
        _sse_queues[task_id] = [q for q in _sse_queues[task_id] if q is not queue]
        if not _sse_queues[task_id]:
            del _sse_queues[task_id]


async def broadcast_dashboard(event_type: str, **data):
    """Broadcast dashboard updates to all WebSocket clients."""
    await emit(event_type, **data)
