"""Event history."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Event, to_utc_naive
from ..pipeline.manager import event_to_dict

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
def list_events(
    camera: str | None = None,
    label: str | None = None,
    rule: str | None = None,
    since: datetime | None = None,
    unacknowledged: bool = False,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    q = select(Event)
    if camera:
        q = q.where(Event.camera_id == camera)
    if label:
        q = q.where(Event.label == label)
    if rule:
        q = q.where(Event.rule_id == rule)
    if since:
        q = q.where(Event.created_at >= to_utc_naive(since))
    if unacknowledged:
        q = q.where(Event.acknowledged.is_(False))
    total = session.scalar(select(func.count()).select_from(q.subquery()))
    rows = session.scalars(q.order_by(Event.created_at.desc()).limit(min(limit, 500)).offset(offset)).all()
    return {"total": total, "items": [event_to_dict(e) for e in rows]}


@router.get("/stats")
def stats(session: Session = Depends(get_session)):
    by_label = session.execute(select(Event.label, func.count()).group_by(Event.label)).all()
    by_camera = session.execute(select(Event.camera_id, func.count()).group_by(Event.camera_id)).all()
    open_count = session.scalar(select(func.count()).where(Event.acknowledged.is_(False)))
    return {
        "by_label": dict(by_label),
        "by_camera": dict(by_camera),
        "unacknowledged": open_count,
    }


@router.post("/ack-all")
def acknowledge_all(camera: str | None = None, session: Session = Depends(get_session)):
    """Clear open alerts by marking them acknowledged. History is kept on the Events page."""
    q = update(Event).where(Event.acknowledged.is_(False)).values(acknowledged=True)
    if camera:
        q = q.where(Event.camera_id == camera)
    cleared = session.execute(q).rowcount
    session.commit()
    return {"cleared": cleared}


@router.get("/{event_id}")
def get_event(event_id: int, session: Session = Depends(get_session)):
    e = session.get(Event, event_id)
    if not e:
        raise HTTPException(404, "Event not found")
    return event_to_dict(e)


@router.post("/{event_id}/ack")
def acknowledge(event_id: int, session: Session = Depends(get_session)):
    e = session.get(Event, event_id)
    if not e:
        raise HTTPException(404, "Event not found")
    e.acknowledged = True
    session.commit()
    return event_to_dict(e)
