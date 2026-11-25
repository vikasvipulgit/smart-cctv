"""WebSocket hub: pushes live events to every open dashboard (web, and later mobile/desktop)."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

log = logging.getLogger(__name__)


class WebSocketHub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def _broadcast(self, message: str) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def broadcast_threadsafe(self, payload: dict) -> None:
        """Called from camera worker threads."""
        if self.loop is None or not self.clients:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(json.dumps(payload, default=str)), self.loop)


hub = WebSocketHub()
