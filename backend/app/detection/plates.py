"""Number plate reading (Phase 2).

Current version: runs EasyOCR on the lower part of a vehicle box (PLATE_OCR=1).
Next step for production accuracy: train a YOLO *plate* detector on Indian plates,
crop the plate, then OCR only the crop.
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

import numpy as np

log = logging.getLogger(__name__)

# Indian plate e.g. MH12AB1234, DL3CAF0001, KA01M1234, and BH series 22BH1234AA
INDIAN_PLATE_RE = re.compile(r"^([A-Z]{2}\d{1,2}[A-Z]{0,3}\d{4}|\d{2}BH\d{4}[A-Z]{1,2})$")

# common OCR confusions, applied by position-insensitive cleanup
_OCR_FIX = str.maketrans({"O": "0", "I": "1", "Z": "2", "S": "5", "B": "8"})


def normalize_plate(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def looks_like_indian_plate(text: str) -> bool:
    return bool(INDIAN_PLATE_RE.match(normalize_plate(text)))


def plate_similarity(a: str, b: str) -> float:
    """0..1 similarity, tolerant of typical OCR mistakes (O/0, I/1, ...)."""
    na, nb = normalize_plate(a), normalize_plate(b)
    if not na or not nb:
        return 0.0
    raw = SequenceMatcher(None, na, nb).ratio()
    fixed = SequenceMatcher(None, na.translate(_OCR_FIX), nb.translate(_OCR_FIX)).ratio()
    return max(raw, fixed)


def plate_matches(read: str | None, watchlist: list[str], threshold: float = 0.8) -> str | None:
    """Return the watchlist entry that matches the plate read, if any."""
    if not read:
        return None
    best, best_score = None, 0.0
    for entry in watchlist:
        score = plate_similarity(read, entry)
        if score > best_score:
            best, best_score = entry, score
    return best if best_score >= threshold else None


class PlateReader:
    def __init__(self) -> None:
        from .text import get_reader  # shares one EasyOCR model with the text scanner

        self.reader = get_reader()
        if self.reader is not None:
            log.info("Plate OCR enabled (EasyOCR)")

    def read(self, frame: np.ndarray, bbox: tuple[int, int, int, int]) -> str | None:
        if self.reader is None:
            return None
        x1, y1, x2, y2 = bbox
        h = y2 - y1
        crop = frame[max(0, y1 + h // 2) : y2, max(0, x1) : x2]  # plates sit in the lower half
        if crop.size == 0 or crop.shape[0] < 12 or crop.shape[1] < 30:
            return None
        try:
            from .text import readtext

            results = readtext(crop, allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
        except Exception as exc:
            log.debug("OCR failed: %s", exc)
            return None
        candidates = [normalize_plate(t) for _, t, conf in results if conf > 0.3]
        joined = "".join(candidates)
        for cand in [*candidates, joined]:
            if looks_like_indian_plate(cand):
                return cand
        return joined if len(joined) >= 6 else None
