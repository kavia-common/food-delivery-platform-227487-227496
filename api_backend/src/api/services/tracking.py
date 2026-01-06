from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, DefaultDict, Set
from uuid import UUID

from fastapi import WebSocket


@dataclass(frozen=True)
class TrackingMessage:
    """Message pushed to tracking subscribers."""
    type: str
    payload: Dict[str, Any]


class TrackingHub:
    """In-memory pub/sub hub keyed by order_id.

    Note: This is per-process and intended for a single backend instance.
    For multi-instance deployments, replace with Redis/pubsub.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._subs: DefaultDict[str, Set[WebSocket]] = DefaultDict(set)

    async def subscribe(self, order_id: UUID, ws: WebSocket) -> None:
        async with self._lock:
            self._subs[str(order_id)].add(ws)

    async def unsubscribe(self, order_id: UUID, ws: WebSocket) -> None:
        async with self._lock:
            self._subs[str(order_id)].discard(ws)
            if not self._subs[str(order_id)]:
                self._subs.pop(str(order_id), None)

    async def publish(self, order_id: UUID, message: TrackingMessage) -> None:
        async with self._lock:
            subscribers = list(self._subs.get(str(order_id), set()))
        dead: list[WebSocket] = []
        for ws in subscribers:
            try:
                await ws.send_text(json.dumps({"type": message.type, "payload": message.payload}))
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._subs.get(str(order_id), set()).discard(ws)


tracking_hub = TrackingHub()
