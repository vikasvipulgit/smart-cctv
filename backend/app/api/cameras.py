"""Camera status, live MJPEG stream and snapshots."""
from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config_store import Zone, normalise_zones, save_camera_enabled, save_camera_zones
from ..pipeline.manager import pipeline

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


@router.get("")
def list_cameras():
    return pipeline.camera_status()


@router.post("/restart")
def restart_cameras():
    """Re-read cameras.yaml and restart all camera workers."""
    pipeline.restart_cameras()
    return {"ok": True, "cameras": len(pipeline.workers)}


@router.patch("/{camera_id}/enabled")
def set_camera_enabled(camera_id: str, enabled: bool):
    """Turn one camera on or off. Saved to cameras.yaml; other cameras keep running."""
    cam = next((c for c in pipeline.cameras if c.id == camera_id), None)
    if cam is None:
        raise HTTPException(404, f"Unknown camera {camera_id!r}")
    if enabled:
        missing = re.findall(r"\$\{(\w+)\}", cam.resolved_source)  # expandvars leaves unset vars as-is
        if missing:
            raise HTTPException(400, f"Set {', '.join(missing)} in .env first, then restart the backend")
    try:
        save_camera_enabled(camera_id, enabled)
    except KeyError as exc:
        raise HTTPException(409, f"Camera {camera_id!r} is no longer in cameras.yaml; reload cameras first") from exc
    pipeline.set_enabled(camera_id, enabled)
    return next(c for c in pipeline.camera_status() if c["id"] == camera_id)


def _worker(camera_id: str):
    w = pipeline.workers.get(camera_id)
    if not w:
        raise HTTPException(404, f"Camera {camera_id!r} not running")
    return w


class ZonesIn(BaseModel):
    zones: list[Zone]


@router.put("/{camera_id}/zones")
def update_zones(camera_id: str, body: ZonesIn):
    """Replace a camera's zones (from the browser zone editor). Saved to cameras.yaml and
    applied to the running worker straight away."""
    if not any(c.id == camera_id for c in pipeline.cameras):
        raise HTTPException(404, f"Unknown camera {camera_id!r}")
    try:
        zones = normalise_zones(body.zones)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        save_camera_zones(camera_id, zones)
    except KeyError as exc:
        raise HTTPException(409, f"Camera {camera_id!r} is no longer in cameras.yaml; reload cameras first") from exc
    pipeline.set_zones(camera_id, zones)
    return {"ok": True, "zones": [z.model_dump() for z in zones]}


@router.get("/{camera_id}/snapshot")
def snapshot(camera_id: str, raw: bool = False):
    """Latest frame as JPEG. raw=true skips the zone/box overlay."""
    w = _worker(camera_id)
    jpeg = w.raw_jpeg() if raw else w.latest_jpeg()
    if not jpeg:
        raise HTTPException(503, "No frame yet")
    return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/{camera_id}/stream")
async def mjpeg_stream(camera_id: str):
    """Annotated live view as MJPEG: works in any <img> tag, no extra streaming server needed."""
    worker = _worker(camera_id)

    async def frames():
        last = None
        while not worker.stopped:  # ends when the camera is turned off or restarted
            jpeg = worker.latest_jpeg()
            if jpeg is not None and jpeg is not last:
                last = jpeg
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store"})
