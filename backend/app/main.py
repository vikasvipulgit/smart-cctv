"""Smart CCTV backend - run with:  uvicorn app.main:app --reload  (from the backend/ folder)."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .alerts.dispatcher import dispatcher
from .alerts.hub import hub
from .api import cameras, events, rules, search
from .config import PROJECT_DIR, settings
from .db import init_db
from .pipeline.manager import pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("smart-cctv")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    hub.loop = asyncio.get_running_loop()
    pipeline.start()
    yield
    pipeline.stop()
    dispatcher.shutdown()


app = FastAPI(title="Smart CCTV", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cameras.router)
app.include_router(events.router)
app.include_router(rules.router)
app.include_router(search.router)
app.mount("/media", StaticFiles(directory=settings.data_dir), name="media")


@app.get("/api/health")
def health():
    return {"status": "ok", "cameras": len(pipeline.workers), "detector": settings.detector}


@app.websocket("/ws/events")
async def events_ws(ws: WebSocket):
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keep-alive pings from the client
    except WebSocketDisconnect:
        hub.disconnect(ws)


# Serve the built web dashboard (frontend/dist) from the same server in production.
_dist = PROJECT_DIR / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
