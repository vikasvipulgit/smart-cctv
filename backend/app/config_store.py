"""Load and save cameras.yaml / rules.yaml.

Camera sources may reference environment variables, e.g. source: "${GATE_RTSP_URL}",
so passwords stay in .env and never in the YAML file.
"""
from __future__ import annotations

import os
import re
import threading
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from .config import settings

_lock = threading.Lock()


ZoneAnchor = Literal["bottom", "center", "overlap"]


class Zone(BaseModel):
    name: str
    # polygon points, normalised 0..1 (x, y) so they work at any resolution
    points: list[list[float]]
    # When an object counts as inside:
    #   bottom  - bottom-centre of its box (feet/wheels) is inside. Best for cameras looking at the ground.
    #   center  - centre of its box is inside.
    #   overlap - at least 25% of its box is inside. Best for webcams/close-ups where people are cut off.
    anchor: ZoneAnchor = "bottom"


class CameraConfig(BaseModel):
    id: str
    name: str
    source: str  # rtsp://..., webcam index ("0"), video file path, or "synthetic"
    enabled: bool = True
    fps: float = 6.0  # frames analysed per second
    zones: list[Zone] = Field(default_factory=list)

    @property
    def resolved_source(self) -> str:
        return os.path.expandvars(self.source)


class TimeWindow(BaseModel):
    start: str  # "22:00"
    end: str  # "06:00" (overnight windows allowed)


class RuleConfig(BaseModel):
    id: str
    name: str
    enabled: bool = True
    cameras: list[str] = Field(default_factory=list)  # empty = all cameras
    classes: list[str] = Field(default_factory=list)  # YOLO labels, empty = any
    zone: str | None = None  # zone name, None = whole frame
    colors: list[str] = Field(default_factory=list)  # e.g. ["white"]
    plates: list[str] = Field(default_factory=list)  # watchlist, fuzzy matched
    min_dwell_seconds: float = 0.0  # loitering: must stay this long in the zone
    time_window: TimeWindow | None = None
    cooldown_seconds: float = 60.0
    min_confidence: float = 0.0
    channels: list[str] = Field(default_factory=lambda: ["websocket"])  # websocket telegram email sms push
    # Text / number reading: a regex the text read in the frame must contain, e.g. \d{2,} for any
    # number with 2+ digits. Turns on OCR for the rule's cameras. Text rules ignore `classes`.
    text_pattern: str | None = None
    # Arrival mode: one alert when matching objects appear on a camera; re-arms only after nothing
    # has matched for cooldown_seconds. Default (False) is one alert per tracked object.
    per_camera: bool = False
    # Alert message, with placeholders {text} {label} {camera} {zone} {plate} {rule}
    message: str | None = None

    @field_validator("text_pattern")
    @classmethod
    def _valid_regex(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"text_pattern is not a valid regular expression: {exc}") from exc
        return v


def _read_yaml(path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_cameras() -> list[CameraConfig]:
    data = _read_yaml(settings.cameras_file)
    return [CameraConfig(**c) for c in data.get("cameras", [])]


def load_rules() -> list[RuleConfig]:
    data = _read_yaml(settings.rules_file)
    return [RuleConfig(**r) for r in data.get("rules", [])]


MAX_ZONE_NAME = 40


def normalise_zones(zones: list[Zone]) -> list[Zone]:
    """Validate zones from the editor: unique non-empty names, >= 3 points, coords clamped to 0..1.

    Raises ValueError with a message that is safe to show to the user.
    """
    out: list[Zone] = []
    seen: set[str] = set()
    for i, z in enumerate(zones, start=1):
        name = z.name.strip()
        if not name:
            raise ValueError(f"Zone {i} has no name")
        if len(name) > MAX_ZONE_NAME:
            raise ValueError(f"Zone name {name!r} is longer than {MAX_ZONE_NAME} characters")
        if name.lower() in seen:
            raise ValueError(f"Two zones are called {name!r}; zone names must be unique")
        seen.add(name.lower())
        if len(z.points) < 3:
            raise ValueError(f"Zone {name!r} needs at least 3 points")
        points: list[list[float]] = []
        for p in z.points:
            if len(p) != 2:
                raise ValueError(f"Zone {name!r} has a point that is not [x, y]")
            points.append([round(min(1.0, max(0.0, float(v))), 4) for v in p])
        out.append(Zone(name=name, points=points, anchor=z.anchor))
    return out


def _zones_yaml(zones: list[Zone]):
    """Zones as ruamel nodes, points in flow style: points: [[0.1, 0.2], [0.3, 0.4], ...]."""
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    seq = CommentedSeq()
    for z in zones:
        pts = CommentedSeq()
        for x, y in z.points:
            p = CommentedSeq([x, y])
            p.fa.set_flow_style()
            pts.append(p)
        pts.fa.set_flow_style()
        m = CommentedMap()
        m["name"] = z.name
        m["points"] = pts
        if z.anchor != "bottom":  # keep the file short for the default
            m["anchor"] = z.anchor
        seq.append(m)
    if not zones:
        seq.fa.set_flow_style()  # zones: []
    return seq


def _round_trip_yaml():
    from ruamel.yaml import YAML

    yml = YAML()  # round-trip mode keeps comments and quoting
    yml.preserve_quotes = True
    yml.width = 4096
    yml.indent(mapping=2, sequence=4, offset=2)
    return yml


def _edit_camera(camera_id: str, edit) -> None:
    """Load cameras.yaml with comments, call edit(camera_mapping), write it back atomically.
    Raises KeyError if the camera is not in the file."""
    yml = _round_trip_yaml()
    path = settings.cameras_file
    with _lock:
        with open(path, "r", encoding="utf-8") as fh:
            doc = yml.load(fh)
        cams = (doc or {}).get("cameras") or []
        cam = next((c for c in cams if str(c.get("id")) == camera_id), None)
        if cam is None:
            raise KeyError(camera_id)
        edit(cam)
        tmp = path.with_suffix(".yaml.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            yml.dump(doc, fh)
        os.replace(tmp, path)


def save_camera_zones(camera_id: str, zones: list[Zone]) -> None:
    """Replace one camera's zones in cameras.yaml. Everything else in the file (comments,
    other cameras, ${VAR} sources) is kept as written. Raises KeyError if the camera is not in the file."""
    from ruamel.yaml.comments import CommentedSeq

    def edit(cam) -> None:
        old = cam.get("zones")
        new = _zones_yaml(zones)
        # Comments that follow this camera (the next camera's heading, or the commented-out example
        # cameras at the end of the file) are attached by ruamel to the end of the old zones list,
        # and only survive if that same list object is kept. So update it in place. An empty flow
        # list ("zones: []") can't carry end comments; then they go after the zones value instead.
        if isinstance(old, CommentedSeq) and len(new):
            old.clear()
            old.extend(new)
            old.fa.set_block_style()
        else:
            trailing = list(getattr(getattr(old, "ca", None), "end", None) or [])
            if trailing:
                cam.ca.items["zones"] = [None, None, _merge_comments(trailing), None]
            cam["zones"] = new

    _edit_camera(camera_id, edit)


def save_camera_enabled(camera_id: str, enabled: bool) -> None:
    """Set one camera's enabled flag in cameras.yaml, keeping the rest of the file as written."""

    def edit(cam) -> None:
        if "enabled" in cam:
            cam["enabled"] = enabled
        else:  # put it after source, not at the end where trailing comments live
            keys = list(cam.keys())
            cam.insert(keys.index("source") + 1 if "source" in keys else len(keys), "enabled", enabled)

    _edit_camera(camera_id, edit)


def _merge_comments(tokens):
    """Join ruamel comment tokens into one token that can sit after a value."""
    from ruamel.yaml.error import CommentMark
    from ruamel.yaml.tokens import CommentToken

    text = "".join((" " * t.column + t.value) if t.value.lstrip().startswith("#") else t.value for t in tokens)
    return CommentToken("\n" + text, CommentMark(0), None)


def save_rules(rules: list[RuleConfig]) -> None:
    with _lock:
        settings.rules_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"rules": [r.model_dump(exclude_none=True) for r in rules]}
        tmp = settings.rules_file.with_suffix(".yaml.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)
        os.replace(tmp, settings.rules_file)
