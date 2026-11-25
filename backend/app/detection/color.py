"""Dominant colour of an object (e.g. 'white car').

Simple HSV heuristic that works well enough to start. Replace with a trained
colour classifier later for better accuracy at night and under street lights.
"""
from __future__ import annotations

import cv2
import numpy as np


def dominant_color(frame: np.ndarray, bbox: tuple[int, int, int, int]) -> str | None:
    x1, y1, x2, y2 = bbox
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None
    # centre 50% of the box: avoids road, background and windows at the edges
    cw, ch = x2 - x1, y2 - y1
    crop = frame[y1 + ch // 4 : y2 - ch // 4, x1 + cw // 4 : x2 - cw // 4]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float32)
    hue, sat, val = np.median(hsv[:, 0]), np.median(hsv[:, 1]), np.median(hsv[:, 2])
    return hsv_to_name(float(hue), float(sat), float(val))


def hsv_to_name(h: float, s: float, v: float) -> str:
    """OpenCV HSV: h 0-180, s 0-255, v 0-255."""
    if v < 50:
        return "black"
    if s < 40:
        if v > 190:
            return "white"
        if v > 120:
            return "silver"
        return "gray"
    if h < 8 or h >= 170:
        return "red"
    if h < 20:
        return "brown" if v < 150 else "orange"
    if h < 34:
        return "yellow"
    if h < 85:
        return "green"
    if h < 130:
        return "blue"
    if h < 160:
        return "purple"
    return "pink"


COLOR_NAMES = ["black", "white", "silver", "gray", "red", "orange", "brown", "yellow", "green", "blue", "purple", "pink"]
