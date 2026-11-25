"""Database tables."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    """Naive UTC. All timestamps are stored as naive UTC (works the same on SQLite and Postgres)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive(dt: datetime | None) -> datetime | None:
    """Aware -> UTC naive; naive values are assumed to be local time."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def utc_iso(dt: datetime | None) -> str | None:
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt else None


def local_of(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc).astimezone()


class Event(Base):
    """An alert raised by a rule."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    camera_id: Mapped[str] = mapped_column(String(64), index=True)
    rule_id: Mapped[str] = mapped_column(String(64), index=True)
    rule_name: Mapped[str] = mapped_column(String(128))
    label: Mapped[str] = mapped_column(String(64), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    plate: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    text: Mapped[str | None] = mapped_column(String(128), nullable=True)  # number/text read by OCR
    message: Mapped[str | None] = mapped_column(String(256), nullable=True)  # rendered alert message
    zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    track_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[str | None] = mapped_column(String(64), nullable=True)  # "x1,y1,x2,y2"
    snapshot_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    clip_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)


class Sighting(Base):
    """Search index: one row per tracked object (everything seen, not only alerts)."""

    __tablename__ = "sightings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[str] = mapped_column(String(64), index=True)
    track_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label: Mapped[str] = mapped_column(String(64), index=True)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    plate: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    zones: Mapped[str] = mapped_column(Text, default="")  # comma separated
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    max_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    thumbnail_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # CLIP vector (float32)
