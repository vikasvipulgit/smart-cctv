"""Threaded video reader for RTSP cameras, webcams, video files and a synthetic test source.

A background thread always keeps the *latest* frame, so slow AI processing never
builds up a backlog of stale frames. RTSP streams reconnect automatically.
"""
from __future__ import annotations

import logging
import math
import os
import threading
import time

import cv2
import numpy as np

# Prefer TCP for RTSP: far fewer corrupted frames than UDP on Wi-Fi / busy networks.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

log = logging.getLogger(__name__)


class SyntheticSource:
    """Generates a test scene with a moving 'object' so the app runs without a camera."""

    def __init__(self, width: int = 960, height: int = 540) -> None:
        self.w, self.h = width, height
        self.t0 = time.time()

    def read(self) -> tuple[bool, np.ndarray]:
        t = time.time() - self.t0
        frame = np.full((self.h, self.w, 3), (40, 44, 48), dtype=np.uint8)
        cv2.rectangle(frame, (0, int(self.h * 0.6)), (self.w, self.h), (70, 75, 80), -1)  # road
        # object moves left -> right in a 12 s loop
        phase = (t % 12) / 12
        cx = int(self.w * (0.05 + 0.9 * phase))
        cy = int(self.h * (0.55 + 0.1 * math.sin(t)))
        cv2.rectangle(frame, (cx - 40, cy - 90), (cx + 40, cy + 90), (230, 230, 230), -1)
        cv2.putText(frame, "SYNTHETIC TEST SOURCE", (20, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (200, 200, 200), 2)
        cv2.putText(frame, time.strftime("%H:%M:%S"), (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)
        time.sleep(1 / 25)
        return True, frame

    def release(self) -> None:  # API parity with cv2.VideoCapture
        pass

    def isOpened(self) -> bool:  # noqa: N802
        return True


def safe_source(s: str) -> str:
    """Source string with any password hidden, safe for logs and the UI."""
    s = str(s)
    if "@" in s and "://" in s:
        scheme, rest = s.split("://", 1)
        creds, host = rest.split("@", 1)
        user = creds.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host}"
    return s


class VideoStream:
    def __init__(self, source: str, name: str = "camera", reconnect_delay: float = 3.0) -> None:
        self.name = name
        self.raw_source = str(source).strip()
        self.reconnect_delay = reconnect_delay
        self.is_synthetic = self.raw_source.lower() == "synthetic"
        self.is_webcam = self.raw_source.isdigit()
        self.is_network = self.raw_source.lower().startswith(("rtsp://", "rtsps://", "http://", "https://"))
        self.is_file = not (self.is_synthetic or self.is_webcam or self.is_network)

        self._frame: np.ndarray | None = None
        self._frame_ts: float = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.connected = False
        self.last_error: str | None = None

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> "VideoStream":
        self._thread = threading.Thread(target=self._run, name=f"stream-{self.name}", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def read(self) -> tuple[np.ndarray | None, float]:
        with self._lock:
            if self._frame is None:
                return None, 0.0
            return self._frame.copy(), self._frame_ts

    # ------------------------------------------------------------------ internals
    def _open(self):
        if self.is_synthetic:
            return SyntheticSource()
        src = int(self.raw_source) if self.is_webcam else self.raw_source
        cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG) if self.is_network else cv2.VideoCapture(src)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:  # not supported by every backend
            pass
        return cap

    def _run(self) -> None:
        while not self._stop.is_set():
            cap = self._open()
            if not cap.isOpened():
                self.connected = False
                self.last_error = f"Could not open source {self._safe_source()}"
                log.warning("[%s] %s, retrying in %.0fs", self.name, self.last_error, self.reconnect_delay)
                self._stop.wait(self.reconnect_delay)
                continue

            log.info("[%s] connected to %s", self.name, self._safe_source())
            self.connected, self.last_error = True, None
            file_fps = cap.get(cv2.CAP_PROP_FPS) if self.is_file else 0
            frame_interval = 1.0 / file_fps if file_fps and file_fps > 0 else 0.0

            while not self._stop.is_set():
                t_read = time.time()
                ok, frame = cap.read()
                if not ok or frame is None:
                    if self.is_file:  # loop video files
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    self.last_error = "Stream dropped"
                    log.warning("[%s] stream dropped, reconnecting", self.name)
                    break
                with self._lock:
                    self._frame, self._frame_ts = frame, time.time()
                if frame_interval:  # play files at real speed
                    delay = frame_interval - (time.time() - t_read)
                    if delay > 0:
                        time.sleep(delay)

            cap.release()
            self.connected = False
            if not self._stop.is_set():
                self._stop.wait(self.reconnect_delay)

    def _safe_source(self) -> str:
        return safe_source(self.raw_source)
