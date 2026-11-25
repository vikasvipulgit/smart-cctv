"""Save annotated snapshots and thumbnails under data/snapshots/YYYY-MM-DD/."""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from ..config import settings

ZONE_COLOR = (255, 180, 0)
BOX_COLOR = (60, 220, 60)
ALERT_COLOR = (40, 40, 240)


def _day_dir() -> Path:
    d = settings.snapshot_dir / time.strftime("%Y-%m-%d")
    d.mkdir(parents=True, exist_ok=True)
    return d


def relative_media_path(path: Path) -> str:
    """Path relative to data dir, served by the API under /media/."""
    return path.relative_to(settings.data_dir).as_posix()


def save_jpeg(frame: np.ndarray, name: str, quality: int = 85) -> str:
    path = _day_dir() / f"{name}.jpg"
    cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return relative_media_path(path)


def save_thumbnail(frame: np.ndarray, bbox: tuple[int, int, int, int], name: str, pad: int = 20) -> str | None:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    crop = frame[max(0, y1 - pad) : min(h, y2 + pad), max(0, x1 - pad) : min(w, x2 + pad)]
    if crop.size == 0:
        return None
    scale = 240 / max(crop.shape[:2])
    if scale < 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale)
    return save_jpeg(crop, name, quality=80)


def draw_overlay(frame: np.ndarray, camera, detections, alert_track_ids: set | None = None) -> np.ndarray:
    """Draw zones and detection boxes on a copy of the frame."""
    out = frame.copy()
    h, w = out.shape[:2]
    alert_track_ids = alert_track_ids or set()
    for zone in camera.zones:
        pts = np.array([[int(x * w), int(y * h)] for x, y in zone.points], dtype=np.int32)
        cv2.polylines(out, [pts], True, ZONE_COLOR, 2)
        cv2.putText(out, zone.name, tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, ZONE_COLOR, 2)
    for det in detections:
        x1, y1, x2, y2 = det.bbox
        color = ALERT_COLOR if det.track_id in alert_track_ids else BOX_COLOR
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        parts = [det.label]
        if det.track_id is not None:
            parts.append(f"#{det.track_id}")
        if det.color:
            parts.append(det.color)
        if det.plate:
            parts.append(det.plate)
        if det.text:
            parts.append(f'"{det.text}"')
        parts.append(f"{det.confidence:.2f}")
        cv2.putText(out, " ".join(parts), (x1, max(16, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    return out
