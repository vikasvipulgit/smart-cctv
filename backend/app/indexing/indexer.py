"""Search index: records every tracked object (not only alerts) so prompt search
can find things you never set up a rule for.

One Sighting row per (camera, track). Rows are updated at most every few seconds
to keep database writes cheap. Optional CLIP embeddings power semantic search.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import numpy as np

from ..config import settings
from ..db import session_scope
from ..models import Sighting
from ..storage.snapshots import save_thumbnail

log = logging.getLogger(__name__)


class Embedder:
    """CLIP image/text embeddings (EMBEDDINGS=1, needs open_clip_torch)."""

    _instance: "Embedder | None" = None

    def __init__(self) -> None:
        import open_clip
        import torch

        self.torch = torch
        self.model, _, self.preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
        self.tokenizer = open_clip.get_tokenizer("ViT-B-32")
        self.model.eval()

    @classmethod
    def get(cls) -> "Embedder | None":
        if not settings.embeddings:
            return None
        if cls._instance is None:
            try:
                cls._instance = Embedder()
                log.info("CLIP embeddings enabled")
            except Exception as exc:
                log.warning("Embeddings unavailable (%s). pip install -r requirements-optional.txt", exc)
                settings.embeddings = False
                return None
        return cls._instance

    def image(self, bgr: np.ndarray) -> bytes:
        from PIL import Image

        img = Image.fromarray(bgr[:, :, ::-1])
        with self.torch.no_grad():
            v = self.model.encode_image(self.preprocess(img).unsqueeze(0))
            v = v / v.norm(dim=-1, keepdim=True)
        return v[0].cpu().numpy().astype(np.float32).tobytes()

    def text(self, query: str) -> np.ndarray:
        with self.torch.no_grad():
            v = self.model.encode_text(self.tokenizer([query]))
            v = v / v.norm(dim=-1, keepdim=True)
        return v[0].cpu().numpy().astype(np.float32)


class Indexer:
    def __init__(self, camera_id: str, update_every: float = 5.0) -> None:
        self.camera_id = camera_id
        self.update_every = update_every
        self._rows: dict[int, tuple[int, float, set[str]]] = {}  # track_id -> (row id, last write, zones)

    def observe(self, frame: np.ndarray, detections, now_ts: float) -> None:
        now = datetime.fromtimestamp(now_ts, tz=timezone.utc).replace(tzinfo=None)
        for det in detections:
            if det.track_id is None:
                continue
            entry = self._rows.get(det.track_id)
            zones = set(det.zones)
            if entry is None:
                thumb = save_thumbnail(frame, det.bbox, f"{self.camera_id}_t{det.track_id}_{int(now_ts)}")
                embedding = None
                emb = Embedder.get()
                if emb is not None:
                    x1, y1, x2, y2 = det.bbox
                    crop = frame[max(0, y1) : y2, max(0, x1) : x2]
                    if crop.size:
                        embedding = emb.image(crop)
                with session_scope() as s:
                    row = Sighting(
                        camera_id=self.camera_id,
                        track_id=det.track_id,
                        label=det.label,
                        color=det.color,
                        plate=det.plate,
                        zones=",".join(sorted(zones)),
                        first_seen=now,
                        last_seen=now,
                        max_confidence=det.confidence,
                        thumbnail_path=thumb,
                        embedding=embedding,
                    )
                    s.add(row)
                    s.flush()
                    self._rows[det.track_id] = (row.id, now_ts, zones)
                continue

            row_id, last_write, known_zones = entry
            new_zones = zones - known_zones
            if now_ts - last_write < self.update_every and not new_zones and not det.plate:
                continue
            all_zones = known_zones | zones
            with session_scope() as s:
                row = s.get(Sighting, row_id)
                if row is None:
                    self._rows.pop(det.track_id, None)
                    continue
                row.last_seen = now
                row.zones = ",".join(sorted(all_zones))
                row.max_confidence = max(row.max_confidence, det.confidence)
                if det.plate and not row.plate:
                    row.plate = det.plate
                if det.color and not row.color:
                    row.color = det.color
            self._rows[det.track_id] = (row_id, now_ts, all_zones)

        # forget tracks not seen for a minute
        if len(self._rows) > 500:
            cutoff = now_ts - 60
            self._rows = {k: v for k, v in self._rows.items() if v[1] >= cutoff}
