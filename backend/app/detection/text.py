"""Read text and numbers anywhere in the frame (EasyOCR).

Used by rules with `text_pattern` (e.g. a number held up to the camera, a house or gate number,
a token on a screen). Full-frame OCR is far slower than YOLO (~0.4 s per 720p frame on an Apple
M2 GPU, ~2.5 s on CPU), so each camera gets a TextScanner thread that reads the latest frame
every TEXT_OCR_INTERVAL seconds, and only while an enabled rule needs text for that camera.
The camera worker picks the results up with take() and runs them through the normal rules.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Callable

import numpy as np

from ..config import settings
from .detector import Detection

log = logging.getLogger(__name__)

MIN_OCR_CONFIDENCE = 0.3  # drop obvious noise; rules can ask for more with min_confidence

_reader = None
_reader_error: str | None = None
_reader_lock = threading.Lock()  # one model load
_ocr_lock = threading.Lock()  # EasyOCR/torch isn't safe to call from several threads at once


def _ensure_ca_bundle() -> None:
    """EasyOCR downloads its models (~100 MB, first run only) with urllib. The python.org macOS
    build has no CA certificates until 'Install Certificates.command' is run, so point it at
    certifi's bundle (already installed with httpx/requests)."""
    if os.environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi

        os.environ["SSL_CERT_FILE"] = certifi.where()
    except ImportError:
        pass


def get_reader():
    """Shared EasyOCR reader (GPU when available: Apple MPS or CUDA), or None if unavailable."""
    global _reader, _reader_error
    with _reader_lock:
        if _reader is not None or _reader_error is not None:
            return _reader
        try:
            _ensure_ca_bundle()
            import easyocr

            use_gpu = settings.device != "cpu"
            try:
                _reader = easyocr.Reader(["en"], gpu=use_gpu, verbose=False)
            except Exception:
                if not use_gpu:
                    raise
                log.warning("EasyOCR on GPU failed, using CPU", exc_info=True)
                _reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            log.info("Text OCR ready (EasyOCR on %s)", getattr(_reader, "device", "?"))
        except Exception as exc:
            _reader_error = f"Text OCR unavailable: {exc}. Run: pip install easyocr"
            log.warning(_reader_error)
        return _reader


def readtext(image: np.ndarray, **kwargs) -> list:
    """EasyOCR readtext, serialised across threads. [] when OCR is unavailable."""
    reader = get_reader()
    if reader is None:
        return []
    with _ocr_lock:
        return reader.readtext(image, **kwargs)


def read_text_detections(frame: np.ndarray) -> list[Detection]:
    """All text in the frame as label="text" detections (bbox in pixels, text stripped)."""
    out: list[Detection] = []
    for points, value, conf in readtext(frame):
        value = " ".join(str(value).split())
        if not value or conf < MIN_OCR_CONFIDENCE:
            continue
        xs = [int(p[0]) for p in points]
        ys = [int(p[1]) for p in points]
        out.append(Detection(label="text", confidence=float(conf), bbox=(min(xs), min(ys), max(xs), max(ys)), text=value))
    return out


class TextScanner(threading.Thread):
    """Background OCR for one camera. `needed()` says whether any enabled rule wants text."""

    def __init__(self, name: str, read_frame: Callable, needed: Callable[[], bool], interval: float) -> None:
        super().__init__(name=f"ocr-{name}", daemon=True)
        self._read_frame = read_frame
        self._needed = needed
        self.interval = max(interval, 0.2)
        self._stop_evt = threading.Event()
        self._lock = threading.Lock()
        self._pending: list[Detection] | None = None
        self.error: str | None = None

    def stop(self) -> None:
        self._stop_evt.set()

    def take(self) -> list[Detection]:
        """Text read since the last call (each reading is delivered once)."""
        with self._lock:
            pending, self._pending = self._pending, None
        return pending or []

    def run(self) -> None:
        last_ts = 0.0
        while not self._stop_evt.is_set():
            if not self._needed():
                self._stop_evt.wait(1.0)
                continue
            frame, ts = self._read_frame()
            if frame is None or ts == last_ts:
                self._stop_evt.wait(0.2)
                continue
            last_ts = ts
            try:
                dets = read_text_detections(frame)
                self.error = _reader_error
            except Exception as exc:
                self.error = f"Text OCR failed: {exc}"
                log.exception("[%s] text OCR failed", self.name)
                dets = []
            with self._lock:
                self._pending = dets
            self._stop_evt.wait(self.interval)
