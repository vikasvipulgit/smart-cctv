"""Object detection + tracking.

YoloDetector uses Ultralytics YOLO with ByteTrack, so every object keeps the same
track_id across frames (one car = one alert, not hundreds).
MockDetector needs no AI model and is used for testing the pipeline end to end.

Create one detector per camera: tracking state lives inside the model instance.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from ..config import settings

log = logging.getLogger(__name__)

VEHICLE_LABELS = {"car", "truck", "bus", "motorcycle", "bicycle"}


@dataclass
class Detection:
    label: str
    confidence: float
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2 in pixels
    track_id: int | None = None
    color: str | None = None
    plate: str | None = None
    text: str | None = None  # set on label="text" detections from the OCR scanner
    zones: list[str] = field(default_factory=list)

    @property
    def anchor(self) -> tuple[float, float]:
        """Bottom-centre of the box (feet / wheels) - best point for zone tests."""
        x1, y1, x2, y2 = self.bbox
        return (x1 + x2) / 2, float(y2)


class BaseDetector:
    def detect(self, frame: np.ndarray) -> list[Detection]:
        raise NotImplementedError


def _pick_device() -> str:
    if settings.device != "auto":
        return settings.device
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"  # Apple Silicon GPU
    except Exception:
        pass
    return "cpu"


class YoloDetector(BaseDetector):
    def __init__(self, model_path: str | None = None, confidence: float | None = None) -> None:
        from ultralytics import YOLO  # imported lazily: heavy

        self.model = YOLO(model_path or settings.yolo_model)  # downloads weights on first run
        self.confidence = confidence if confidence is not None else settings.confidence
        self.device = _pick_device()
        log.info("YOLO model %s on device %s", model_path or settings.yolo_model, self.device)

    def detect(self, frame: np.ndarray) -> list[Detection]:
        results = self.model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            conf=self.confidence,
            device=self.device,
            verbose=False,
        )
        out: list[Detection] = []
        if not results:
            return out
        r = results[0]
        names = r.names
        boxes = r.boxes
        if boxes is None or len(boxes) == 0:
            return out
        xyxy = boxes.xyxy.cpu().numpy().astype(int)
        confs = boxes.conf.cpu().numpy()
        clss = boxes.cls.cpu().numpy().astype(int)
        ids = boxes.id.cpu().numpy().astype(int) if boxes.id is not None else [None] * len(clss)
        for (x1, y1, x2, y2), c, k, tid in zip(xyxy, confs, clss, ids):
            out.append(
                Detection(
                    label=names[int(k)],
                    confidence=float(c),
                    bbox=(int(x1), int(y1), int(x2), int(y2)),
                    track_id=None if tid is None else int(tid),
                )
            )
        return out


class MockDetector(BaseDetector):
    """Finds the bright moving block drawn by the synthetic source (or any bright blob).

    Lets you test zones, rules, alerts, the dashboard and search without downloading a model.
    """

    def __init__(self, label: str = "person") -> None:
        self.label = label

    def detect(self, frame: np.ndarray) -> list[Detection]:
        import cv2

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        dets = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if w * h < 2000:
                continue
            dets.append(Detection(label=self.label, confidence=0.9, bbox=(x, y, x + w, y + h), track_id=1))
        return dets


def create_detector() -> BaseDetector:
    if settings.detector == "mock":
        return MockDetector()
    return YoloDetector()
