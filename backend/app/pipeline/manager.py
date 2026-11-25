"""Camera workers: frames -> detection -> enrichment -> rules -> events -> alerts.

One worker thread per camera. Each keeps the latest annotated JPEG for the live view.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

import cv2

from ..alerts.dispatcher import dispatcher
from ..config import settings
from ..config_store import CameraConfig, RuleConfig, Zone, load_cameras, load_rules
from ..db import session_scope
from ..detection.color import dominant_color
from ..detection.detector import VEHICLE_LABELS, create_detector
from ..detection.plates import PlateReader
from ..detection.text import TextScanner
from ..indexing.indexer import Indexer
from ..models import Event, local_of, utc_iso
from ..rules.engine import RuleEngine, render_message
from ..storage.snapshots import draw_overlay, save_jpeg
from ..capture.stream import VideoStream, safe_source

log = logging.getLogger(__name__)


def event_to_dict(e: Event) -> dict:
    created = e.created_at
    return {
        "id": e.id,
        "created_at": utc_iso(created),
        "created_at_local": local_of(created).strftime("%d %b %Y %H:%M:%S") if created else "",
        "camera_id": e.camera_id,
        "rule_id": e.rule_id,
        "rule_name": e.rule_name,
        "label": e.label,
        "confidence": round(e.confidence or 0, 3),
        "color": e.color,
        "plate": e.plate,
        "text": e.text,
        "message": e.message,
        "zone": e.zone,
        "track_id": e.track_id,
        "bbox": e.bbox,
        "snapshot_path": e.snapshot_path,
        "snapshot_url": f"/media/{e.snapshot_path}" if e.snapshot_path else None,
        "clip_path": e.clip_path,
        "acknowledged": e.acknowledged,
    }


class CameraWorker(threading.Thread):
    def __init__(self, camera: CameraConfig, engine: RuleEngine, plate_reader: PlateReader | None) -> None:
        super().__init__(name=f"worker-{camera.id}", daemon=True)
        self.camera = camera
        self.engine = engine
        self.plate_reader = plate_reader
        self.stream = VideoStream(camera.resolved_source, name=camera.id)
        self.indexer = Indexer(camera.id)
        self.text_scanner = TextScanner(camera.id, self.stream.read, lambda: engine.needs_text(self.camera.id),
                                        settings.text_ocr_interval)
        self._stop_evt = threading.Event()
        self._jpeg: bytes | None = None
        self._jpeg_lock = threading.Lock()
        self.processing_fps = 0.0
        self.last_frame_ts = 0.0
        self.error: str | None = None
        self.detector = None

    # ---------------------------------------------------------------- public
    @property
    def status(self) -> dict:
        return {
            "id": self.camera.id,
            "name": self.camera.name,
            "enabled": self.camera.enabled,
            "connected": self.stream.connected,
            "source": self.stream._safe_source(),
            "processing_fps": round(self.processing_fps, 1),
            "last_frame_age_s": round(time.time() - self.last_frame_ts, 1) if self.last_frame_ts else None,
            "error": self.error or self.stream.last_error or self.text_scanner.error,
            "zones": [z.model_dump() for z in self.camera.zones],
        }

    def latest_jpeg(self) -> bytes | None:
        with self._jpeg_lock:
            return self._jpeg

    def raw_jpeg(self) -> bytes | None:
        """Latest camera frame without overlays (used by the zone editor)."""
        frame, _ = self.stream.read()
        if frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes() if ok else None

    @property
    def stopped(self) -> bool:
        return self._stop_evt.is_set()

    def stop(self) -> None:
        self._stop_evt.set()
        self.text_scanner.stop()
        self.stream.stop()

    # ---------------------------------------------------------------- loop
    def run(self) -> None:
        try:
            self.detector = create_detector()
        except Exception as exc:
            self.error = f"Detector failed to load: {exc}"
            log.exception("[%s] %s", self.camera.id, self.error)
            return
        self.stream.start()
        self.text_scanner.start()
        interval = 1.0 / max(self.camera.fps, 0.5)
        last_processed_ts = 0.0
        ema = 0.0

        while not self._stop_evt.is_set():
            t0 = time.time()
            frame, frame_ts = self.stream.read()
            if frame is None or frame_ts == last_processed_ts:
                self._stop_evt.wait(0.05)
                continue
            last_processed_ts = frame_ts
            try:
                self._process(frame, frame_ts)
                self.error = None
            except Exception as exc:
                self.error = str(exc)
                log.exception("[%s] processing error", self.camera.id)
            dt = time.time() - t0
            ema = 0.9 * ema + 0.1 * (1 / dt if dt > 0 else 0)
            self.processing_fps = min(ema, self.camera.fps)
            self._stop_evt.wait(max(0.0, interval - dt))

    def _process(self, frame, frame_ts: float) -> None:
        h, w = frame.shape[:2]
        detections = self.detector.detect(frame)

        for det in detections:
            det.zones = RuleEngine.zones_for(det, self.camera, w, h)
            if det.label in VEHICLE_LABELS or settings.detector == "mock":
                det.color = dominant_color(frame, det.bbox)
            if self.plate_reader and det.label in VEHICLE_LABELS:
                det.plate = self.plate_reader.read(frame, det.bbox)

        # numbers/text read by the OCR thread since the last frame (only while a text rule is on)
        for t in self.text_scanner.take():
            t.zones = RuleEngine.zones_for(t, self.camera, w, h)
            detections.append(t)

        self.last_frame_ts = frame_ts
        self.indexer.observe(frame, [d for d in detections if d.text is None], frame_ts)
        matches = self.engine.evaluate(self.camera, detections, frame_ts, datetime.fromtimestamp(frame_ts))

        alert_ids = {m.detection.track_id for m in matches}
        annotated = draw_overlay(frame, self.camera, detections, alert_ids)
        ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            with self._jpeg_lock:
                self._jpeg = buf.tobytes()

        for m in matches:
            self._raise_event(annotated, m)

    def _raise_event(self, annotated, match) -> None:
        det = match.detection
        rule = match.rule
        message = render_message(rule.message, {
            "text": match.matched_text, "label": det.label, "camera": self.camera.name,
            "zone": match.zone, "plate": match.matched_plate or det.plate, "rule": rule.name,
        })
        if message is None and match.matched_text:
            message = f"Read: {match.matched_text}"
        snap = save_jpeg(annotated, f"{self.camera.id}_{match.rule.id}_{int(time.time() * 1000)}")
        with session_scope() as s:
            ev = Event(
                camera_id=self.camera.id,
                rule_id=match.rule.id,
                rule_name=match.rule.name,
                label=det.label,
                confidence=det.confidence,
                color=det.color,
                plate=match.matched_plate or det.plate,
                text=(match.matched_text or "")[:128] or None,
                message=(message or "")[:256] or None,
                zone=match.zone,
                track_id=det.track_id,
                bbox=",".join(map(str, det.bbox)),
                snapshot_path=snap,
            )
            s.add(ev)
            s.flush()
            payload = event_to_dict(ev)
        log.info("[%s] EVENT %s: %s", self.camera.id, match.rule.name, det.label)
        dispatcher.dispatch(payload, match.rule.channels)


class PipelineManager:
    def __init__(self) -> None:
        self.workers: dict[str, CameraWorker] = {}
        self.cameras: list[CameraConfig] = []
        self.engine = RuleEngine(load_rules())
        self.plate_reader = PlateReader() if settings.plate_ocr else None
        self._lock = threading.RLock()  # guards workers/cameras against concurrent start/stop

    def start(self) -> None:
        with self._lock:
            self.cameras = load_cameras()
            for cam in self.cameras:
                if cam.enabled:
                    self._start_worker(cam)
        log.info("Started %d camera worker(s)", len(self.workers))

    def stop(self) -> None:
        with self._lock:
            for w in self.workers.values():
                w.stop()
            self.workers.clear()

    def _start_worker(self, cam: CameraConfig) -> None:
        worker = CameraWorker(cam, self.engine, self.plate_reader)
        self.workers[cam.id] = worker
        worker.start()

    def set_enabled(self, camera_id: str, enabled: bool) -> None:
        """Start or stop one camera without touching the others. Raises KeyError for unknown ids."""
        with self._lock:
            cam = next((c for c in self.cameras if c.id == camera_id), None)
            if cam is None:
                raise KeyError(camera_id)
            cam.enabled = enabled
            if enabled and camera_id not in self.workers:
                self._start_worker(cam)
            elif not enabled and camera_id in self.workers:
                self.workers.pop(camera_id).stop()  # releases the device (webcam light goes off)

    def reload_rules(self, rules: list[RuleConfig] | None = None) -> None:
        self.engine.set_rules(rules if rules is not None else load_rules())

    def restart_cameras(self) -> None:
        with self._lock:
            self.stop()
            self.start()

    def set_zones(self, camera_id: str, zones: list[Zone]) -> None:
        """Swap a camera's zones in place. Workers share the CameraConfig object, so the next
        frame is evaluated against the new zones without restarting the stream."""
        for cam in self.cameras:
            if cam.id == camera_id:
                cam.zones = list(zones)
        w = self.workers.get(camera_id)
        if w is not None:
            w.camera.zones = list(zones)

    def camera_status(self) -> list[dict]:
        out = []
        for cam in self.cameras:
            w = self.workers.get(cam.id)
            if w:
                out.append(w.status)
            else:
                out.append({"id": cam.id, "name": cam.name, "enabled": cam.enabled, "connected": False,
                            "source": safe_source(cam.source), "processing_fps": 0, "last_frame_age_s": None,
                            "error": None,
                            "zones": [z.model_dump() for z in cam.zones]})
        return out


pipeline = PipelineManager()
