"""Rule engine: decides which detections become events.

A rule matches a detection when ALL of its conditions hold:
camera, class, confidence, zone, colour, plate watchlist, text pattern, time window and dwell time.
Cooldowns stop the same object from re-alerting every frame. Rules with per_camera=True alert once
per arrival instead of once per tracked object.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import datetime, time as dtime

from ..config_store import CameraConfig, RuleConfig
from ..detection.detector import Detection
from ..detection.plates import plate_matches


def point_in_polygon(x: float, y: float, polygon: list[list[float]]) -> bool:
    """Ray casting. Coordinates in the same space as the polygon (normalised 0..1)."""
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


OVERLAP_MIN_FRACTION = 0.25  # zone anchor "overlap": share of the box that must be inside
_GRID = 6  # overlap is estimated on a 6x6 grid of points in the box (cheap, no geometry library)


def in_zone(det: Detection, zone, frame_w: int, frame_h: int) -> bool:
    """Is the detection inside the zone, using the zone's anchor mode (bottom | center | overlap)?"""
    fw, fh = max(frame_w, 1), max(frame_h, 1)
    x1, y1, x2, y2 = det.bbox
    anchor = getattr(zone, "anchor", "bottom")
    if anchor == "center":
        return point_in_polygon((x1 + x2) / 2 / fw, (y1 + y2) / 2 / fh, zone.points)
    if anchor == "overlap":
        inside = sum(
            point_in_polygon((x1 + (x2 - x1) * (i + 0.5) / _GRID) / fw, (y1 + (y2 - y1) * (j + 0.5) / _GRID) / fh, zone.points)
            for i in range(_GRID) for j in range(_GRID)
        )
        return inside / (_GRID * _GRID) >= OVERLAP_MIN_FRACTION
    ax, ay = det.anchor  # bottom-centre
    return point_in_polygon(ax / fw, ay / fh, zone.points)


def _parse_hhmm(value: str) -> dtime:
    hh, mm = value.strip().split(":")
    return dtime(int(hh), int(mm))


def in_time_window(now: datetime, start: str, end: str) -> bool:
    s, e, t = _parse_hhmm(start), _parse_hhmm(end), now.time()
    if s <= e:
        return s <= t <= e
    return t >= s or t <= e  # overnight window, e.g. 22:00-06:00


@dataclass
class RuleMatch:
    rule: RuleConfig
    detection: Detection
    zone: str | None
    matched_plate: str | None = None
    matched_text: str | None = None


def render_message(template: str | None, values: dict[str, str | None]) -> str | None:
    """Fill {text} {label} {camera} ... in a rule's message. Plain replace, so braces in the
    template or in OCR text can't do anything clever."""
    if not template:
        return None
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", value or "")
    return out.strip() or None


class RuleEngine:
    def __init__(self, rules: list[RuleConfig]) -> None:
        self._lock = threading.Lock()
        self.rules = rules
        self._last_fired: dict[tuple[str, str, str], float] = {}
        self._first_seen_in_zone: dict[tuple[str, str, str], float] = {}
        self._last_match: dict[tuple[str, str, str], float] = {}  # per_camera (arrival) rules

    def set_rules(self, rules: list[RuleConfig]) -> None:
        with self._lock:
            self.rules = rules
            self._last_fired.clear()
            self._first_seen_in_zone.clear()
            self._last_match.clear()

    def needs_text(self, camera_id: str) -> bool:
        """True if an enabled rule reads text on this camera (so its OCR scanner should run)."""
        with self._lock:
            rules = list(self.rules)
        return any(r.enabled and r.text_pattern and (not r.cameras or camera_id in r.cameras) for r in rules)

    @staticmethod
    def zones_for(det: Detection, camera: CameraConfig, frame_w: int, frame_h: int) -> list[str]:
        return [z.name for z in camera.zones if in_zone(det, z, frame_w, frame_h)]

    def evaluate(
        self,
        camera: CameraConfig,
        detections: list[Detection],
        now_ts: float,
        now_local: datetime | None = None,
    ) -> list[RuleMatch]:
        now_local = now_local or datetime.fromtimestamp(now_ts)
        matches: list[RuleMatch] = []
        with self._lock:
            rules = list(self.rules)
        seen_keys: set[tuple[str, str, str]] = set()

        for rule in rules:
            if not rule.enabled:
                continue
            if rule.cameras and camera.id not in rule.cameras:
                continue
            if rule.time_window and not in_time_window(now_local, rule.time_window.start, rule.time_window.end):
                continue

            for det in detections:
                matched_text = None
                if rule.text_pattern:
                    # text rules only look at OCR readings, whatever `classes` says
                    m = re.search(rule.text_pattern, det.text) if det.text is not None else None
                    if not m:
                        continue
                    matched_text = m.group(0)
                elif det.text is not None:
                    continue  # OCR readings never match ordinary object rules
                elif rule.classes and det.label not in rule.classes:
                    continue
                if det.confidence < rule.min_confidence:
                    continue
                if rule.zone and rule.zone not in det.zones:
                    continue
                if rule.colors and (det.color or "") not in rule.colors:
                    continue
                matched_plate = None
                if rule.plates:
                    matched_plate = plate_matches(det.plate, rule.plates)
                    if not matched_plate:
                        continue

                if rule.per_camera:
                    obj_key = "*"  # the camera as a whole: one alert per arrival
                elif det.text is not None:
                    obj_key = f"text:{matched_text}"  # each different number alerts on its own
                else:
                    obj_key = str(det.track_id) if det.track_id is not None else "untracked"
                key = (rule.id, camera.id, obj_key)
                seen_keys.add(key)

                # dwell / loitering
                first = self._first_seen_in_zone.setdefault(key, now_ts)
                if now_ts - first < rule.min_dwell_seconds:
                    continue

                if rule.per_camera:
                    # still the same visit while something matched within the last cooldown_seconds
                    last_match = self._last_match.get(key)
                    self._last_match[key] = now_ts
                    if last_match is not None and now_ts - last_match < rule.cooldown_seconds:
                        continue
                else:
                    last = self._last_fired.get(key)
                    if last is not None and now_ts - last < rule.cooldown_seconds:
                        continue
                self._last_fired[key] = now_ts
                matches.append(RuleMatch(rule=rule, detection=det, zone=rule.zone,
                                         matched_plate=matched_plate, matched_text=matched_text))

        # objects that left the zone restart their dwell timer
        with self._lock:
            for key in list(self._first_seen_in_zone):
                if key[1] == camera.id and key not in seen_keys:
                    del self._first_seen_in_zone[key]
        return matches
