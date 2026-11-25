"""Natural-language prompts -> structured filters, rules and answers.

Works out of the box with a keyword parser (no AI needed). Set LLM_PROVIDER=anthropic
(or ollama) in .env for much better understanding of free-form prompts and for
"ask about this snapshot" answers from a vision-language model.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

import httpx
import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..config_store import RuleConfig, load_cameras
from ..detection.color import COLOR_NAMES
from ..indexing.indexer import Embedder
from ..models import Event, Sighting, local_of, to_utc_naive, utc_iso

log = logging.getLogger(__name__)

# word -> YOLO labels
LABEL_WORDS: dict[str, list[str]] = {
    "person": ["person"], "people": ["person"], "man": ["person"], "woman": ["person"], "someone": ["person"],
    "anyone": ["person"], "intruder": ["person"], "worker": ["person"], "human": ["person"],
    "car": ["car"], "cars": ["car"], "suv": ["car"], "sedan": ["car"], "taxi": ["car"],
    "vehicle": ["car", "truck", "bus", "motorcycle"], "vehicles": ["car", "truck", "bus", "motorcycle"],
    "truck": ["truck"], "trucks": ["truck"], "lorry": ["truck"], "tempo": ["truck"],
    "bus": ["bus"], "buses": ["bus"],
    "bike": ["motorcycle", "bicycle"], "motorcycle": ["motorcycle"], "motorbike": ["motorcycle"],
    "scooter": ["motorcycle"], "bicycle": ["bicycle"], "cycle": ["bicycle"],
    "dog": ["dog"], "cat": ["cat"], "cow": ["cow"],
    "bag": ["backpack", "handbag", "suitcase"], "backpack": ["backpack"], "suitcase": ["suitcase"],
}
COLOR_ALIASES = {"grey": "gray", "golden": "yellow", "maroon": "red"}


class SearchFilters(BaseModel):
    labels: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    cameras: list[str] = Field(default_factory=list)
    zones: list[str] = Field(default_factory=list)
    plate: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    hour_from: int | None = None  # local hour-of-day filter, e.g. "after 6 pm"
    hour_to: int | None = None
    semantic_text: str | None = None  # free text for CLIP search
    source: str = "keywords"  # keywords | llm


# ---------------------------------------------------------------------- keyword parser
def _hour(num: str, ampm: str | None) -> int:
    h = int(num) % 24
    if ampm:
        ampm = ampm.lower()
        if ampm.startswith("p") and h < 12:
            h += 12
        if ampm.startswith("a") and h == 12:
            h = 0
    return h


def parse_keywords(prompt: str, now: datetime | None = None) -> SearchFilters:
    now = now or datetime.now()
    text = prompt.lower()
    words = re.findall(r"[a-z0-9]+", text)
    f = SearchFilters()

    for w in words:
        if w in LABEL_WORDS:
            for lab in LABEL_WORDS[w]:
                if lab not in f.labels:
                    f.labels.append(lab)
        c = COLOR_ALIASES.get(w, w)
        if c in COLOR_NAMES and c not in f.colors:
            f.colors.append(c)

    cams = load_cameras()
    for cam in cams:
        if cam.id.lower() in text or cam.name.lower() in text:
            f.cameras.append(cam.id)
        for z in cam.zones:
            if z.name.lower() in text or z.name.lower().replace("_", " ") in text:
                f.zones.append(z.name)

    m = re.search(r"\b([a-z]{2}\s?\d{1,2}\s?[a-z]{0,3}\s?\d{4})\b", text)
    if m:
        f.plate = re.sub(r"\s", "", m.group(1)).upper()

    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "yesterday" in text:
        f.since, f.until = midnight - timedelta(days=1), midnight
    elif "today" in text or "tonight" in text:
        f.since = midnight
    elif "this week" in text or "last 7 days" in text:
        f.since = now - timedelta(days=7)
    m = re.search(r"last\s+(\d+)\s*(minute|min|hour|hr|day)s?", text)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = timedelta(minutes=n) if unit.startswith("min") else timedelta(hours=n) if unit.startswith("h") else timedelta(days=n)
        f.since, f.until = now - delta, None
    elif re.search(r"last\s+hour", text):
        f.since = now - timedelta(hours=1)

    m = re.search(r"(?:after|from)\s+(\d{1,2})(?::\d{2})?\s*(am|pm)?", text)
    if m:
        f.hour_from = _hour(m.group(1), m.group(2))
    m = re.search(r"(?:before|until|till)\s+(\d{1,2})(?::\d{2})?\s*(am|pm)?", text)
    if m:
        f.hour_to = _hour(m.group(1), m.group(2))
    if re.search(r"(?:after|from|past)\s+midnight", text) and f.hour_from is None:
        f.hour_from = 0
        f.hour_to = f.hour_to if f.hour_to is not None else 6
    elif re.search(r"\b(?:night|tonight)\b", text) and f.hour_from is None:
        f.hour_from, f.hour_to = 20, 6

    f.semantic_text = prompt.strip()
    return f


# ---------------------------------------------------------------------- LLM helpers
LLM_SYSTEM = (
    "You convert CCTV search requests into JSON filters. Reply with JSON only, keys: "
    "labels (COCO class names like person, car, truck, bus, motorcycle, bicycle, dog, backpack), "
    "colors (from: " + ", ".join(COLOR_NAMES) + "), cameras (ids), zones (names), plate (string or null), "
    "since and until (ISO 8601 local datetimes or null), hour_from and hour_to (0-23 or null), "
    "semantic_text (short visual description for image search). Current local time: {now}. "
    "Known cameras and zones: {cams}."
)


def _anthropic(messages: list[dict], system: str, max_tokens: int = 600) -> str:
    r = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": settings.anthropic_model, "max_tokens": max_tokens, "system": system, "messages": messages},
        timeout=60,
    )
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json().get("content", []))


def _ollama(prompt: str, system: str, images: list[str] | None = None) -> str:
    body: dict[str, Any] = {"model": settings.ollama_model, "system": system, "prompt": prompt, "stream": False}
    if images:
        body["images"] = images
    r = httpx.post(f"{settings.ollama_url}/api/generate", json=body, timeout=120)
    r.raise_for_status()
    return r.json().get("response", "")


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


def parse_prompt(prompt: str) -> SearchFilters:
    if settings.llm_provider in {"anthropic", "ollama"}:
        try:
            cams = [{"id": c.id, "name": c.name, "zones": [z.name for z in c.zones]} for c in load_cameras()]
            system = LLM_SYSTEM.format(now=datetime.now().isoformat(timespec="minutes"), cams=json.dumps(cams))
            if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
                raw = _anthropic([{"role": "user", "content": prompt}], system)
            else:
                raw = _ollama(prompt, system)
            data = _extract_json(raw)
            f = SearchFilters(**{k: v for k, v in data.items() if k in SearchFilters.model_fields})
            f.source = "llm"
            return f
        except Exception as exc:
            log.warning("LLM parsing failed, falling back to keywords: %s", exc)
    return parse_keywords(prompt)


# ---------------------------------------------------------------------- search
def _hour_ok(dt: datetime, hour_from: int | None, hour_to: int | None) -> bool:
    if hour_from is None and hour_to is None:
        return True
    h = local_of(dt).hour
    lo = 0 if hour_from is None else hour_from
    hi = 24 if hour_to is None else hour_to
    return lo <= h < hi if lo <= hi else (h >= lo or h < hi)


def search(session: Session, f: SearchFilters, limit: int = 60) -> dict:
    q = select(Sighting).order_by(Sighting.last_seen.desc())
    if f.labels:
        q = q.where(Sighting.label.in_(f.labels))
    if f.colors:
        q = q.where(Sighting.color.in_(f.colors))
    if f.cameras:
        q = q.where(Sighting.camera_id.in_(f.cameras))
    if f.plate:
        q = q.where(Sighting.plate.contains(f.plate))
    if f.since:
        q = q.where(Sighting.last_seen >= to_utc_naive(f.since))
    if f.until:
        q = q.where(Sighting.first_seen <= to_utc_naive(f.until))
    rows = session.scalars(q.limit(2000)).all()

    rows = [r for r in rows if _hour_ok(r.first_seen, f.hour_from, f.hour_to)]
    if f.zones:
        rows = [r for r in rows if set(r.zones.split(",")) & set(f.zones)]

    # semantic re-ranking with CLIP when available
    emb = Embedder.get()
    scores: dict[int, float] = {}
    if emb is not None and f.semantic_text:
        qv = emb.text(f.semantic_text)
        for r in rows:
            if r.embedding:
                scores[r.id] = float(np.dot(np.frombuffer(r.embedding, dtype=np.float32), qv))
        rows.sort(key=lambda r: scores.get(r.id, -1.0), reverse=True)

    rows = rows[:limit]
    ev_q = select(Event).order_by(Event.created_at.desc()).limit(limit)
    if f.labels:
        ev_q = ev_q.where(Event.label.in_(f.labels))
    if f.cameras:
        ev_q = ev_q.where(Event.camera_id.in_(f.cameras))
    if f.since:
        ev_q = ev_q.where(Event.created_at >= to_utc_naive(f.since))
    if f.until:
        ev_q = ev_q.where(Event.created_at <= to_utc_naive(f.until))
    events = [e for e in session.scalars(ev_q).all() if _hour_ok(e.created_at, f.hour_from, f.hour_to)]

    return {
        "sightings": [
            {
                "id": r.id, "camera_id": r.camera_id, "track_id": r.track_id, "label": r.label, "color": r.color,
                "plate": r.plate, "zones": [z for z in r.zones.split(",") if z],
                "first_seen": utc_iso(r.first_seen), "last_seen": utc_iso(r.last_seen),
                "confidence": round(r.max_confidence, 3),
                "thumbnail_url": f"/media/{r.thumbnail_path}" if r.thumbnail_path else None,
                "score": scores.get(r.id),
            }
            for r in rows
        ],
        "events": events,
    }


# ---------------------------------------------------------------------- prompt -> rule
def rule_from_prompt(prompt: str) -> RuleConfig:
    """'Alert me if anyone goes near the gate after midnight' -> a proposed rule (user confirms in UI)."""
    f = parse_prompt(prompt)
    text = prompt.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", text)[:40].strip("_") or "custom_rule"
    channels = ["websocket"]
    for ch in ("telegram", "email", "sms"):
        if ch in text:
            channels.append(ch)
    if channels == ["websocket"]:
        channels.append("telegram")
    time_window = None
    if f.hour_from is not None or "midnight" in text:
        start = f.hour_from if f.hour_from is not None else 0
        end = f.hour_to if f.hour_to is not None else 6
        time_window = {"start": f"{start:02d}:00", "end": f"{end:02d}:00"}
    dwell = 0.0
    m = re.search(r"(?:more than|over|longer than|for)\s+(\d+)\s*(second|sec|minute|min)", text)
    if m:
        dwell = float(m.group(1)) * (60 if m.group(2).startswith("min") else 1)
    elif "loiter" in text:
        dwell = 30.0
    return RuleConfig(
        id=slug,
        name=prompt.strip()[:80],
        enabled=True,
        cameras=f.cameras,
        classes=f.labels,
        zone=f.zones[0] if f.zones else None,
        colors=f.colors,
        plates=[f.plate] if f.plate else [],
        min_dwell_seconds=dwell,
        time_window=time_window,
        cooldown_seconds=60,
        channels=channels,
    )


# ---------------------------------------------------------------------- ask a VLM about a snapshot
def ask_about_image(image_path, question: str) -> str:
    data = base64.b64encode(image_path.read_bytes()).decode()
    system = "You are a CCTV analyst. Answer briefly and only from what is visible in the image. Say if unsure."
    if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
        return _anthropic(
            [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
                {"type": "text", "text": question},
            ]}],
            system,
        )
    if settings.llm_provider == "ollama":
        return _ollama(question, system, images=[data])
    raise RuntimeError("No vision model configured. Set LLM_PROVIDER=anthropic or ollama in .env")
