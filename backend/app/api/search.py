"""Natural-language prompt features."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..config_store import RuleConfig
from ..db import get_session
from ..models import Event
from ..pipeline.manager import event_to_dict
from ..search import prompt as P

router = APIRouter(prefix="/api/search", tags=["search"])


class PromptIn(BaseModel):
    prompt: str
    limit: int = 60


class AskIn(BaseModel):
    event_id: int
    question: str


@router.post("")
def search(body: PromptIn, session: Session = Depends(get_session)):
    """'white car at the gate yesterday after 6 pm' -> filters + matching sightings and events."""
    filters = P.parse_prompt(body.prompt)
    result = P.search(session, filters, limit=body.limit)
    return {
        "filters": filters.model_dump(mode="json"),
        "sightings": result["sightings"],
        "events": [event_to_dict(e) for e in result["events"]],
    }


@router.post("/rule", response_model=RuleConfig)
def propose_rule(body: PromptIn):
    """'Alert me if anyone is at the gate after midnight' -> proposed rule. Save it with POST /api/rules."""
    return P.rule_from_prompt(body.prompt)


@router.post("/ask")
def ask(body: AskIn, session: Session = Depends(get_session)):
    """Ask a vision-language model a question about an event's snapshot."""
    e = session.get(Event, body.event_id)
    if not e or not e.snapshot_path:
        raise HTTPException(404, "Event or snapshot not found")
    path = settings.data_dir / e.snapshot_path
    try:
        answer = P.ask_about_image(path, body.question)
    except RuntimeError as exc:
        raise HTTPException(501, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Vision model error: {exc}")
    return {"answer": answer}


@router.get("/capabilities")
def capabilities():
    return {
        "llm_provider": settings.llm_provider,
        "llm_ready": (settings.llm_provider == "anthropic" and bool(settings.anthropic_api_key)) or settings.llm_provider == "ollama",
        "embeddings": settings.embeddings,
        "plate_ocr": settings.plate_ocr,
        "detector": settings.detector,
    }
