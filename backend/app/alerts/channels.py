"""Alert channels. Each one is skipped quietly when it isn't configured in .env."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

import httpx

from ..config import settings
from .hub import hub

log = logging.getLogger(__name__)


def _snapshot_file(event: dict) -> Path | None:
    rel = event.get("snapshot_path")
    if not rel:
        return None
    p = settings.data_dir / rel
    return p if p.exists() else None


def format_text(event: dict) -> str:
    parts = [f"🚨 {event['rule_name']}"]
    if event.get("message"):
        parts.append(event["message"])
    parts += [f"Camera: {event['camera_id']}", f"Object: {event['label']}"]
    if event.get("text"):
        parts.append(f"Read: {event['text']}")
    if event.get("color"):
        parts.append(f"Colour: {event['color']}")
    if event.get("plate"):
        parts.append(f"Plate: {event['plate']}")
    if event.get("zone"):
        parts.append(f"Zone: {event['zone']}")
    parts.append(f"Time: {event['created_at_local']}")
    parts.append(f"{settings.public_base_url.rstrip('/')}/#/events/{event['id']}")
    return "\n".join(parts)


def send_websocket(event: dict) -> None:
    hub.broadcast_threadsafe({"type": "event", "event": event})


def send_telegram(event: dict) -> None:
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        log.debug("Telegram not configured; skipping")
        return
    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    text = format_text(event)
    snap = _snapshot_file(event)
    with httpx.Client(timeout=15) as client:
        if snap:
            with open(snap, "rb") as fh:
                r = client.post(f"{base}/sendPhoto", data={"chat_id": settings.telegram_chat_id, "caption": text[:1000]}, files={"photo": fh})
        else:
            r = client.post(f"{base}/sendMessage", data={"chat_id": settings.telegram_chat_id, "text": text})
        if r.status_code != 200:
            log.warning("Telegram error %s: %s", r.status_code, r.text[:200])


def send_email(event: dict) -> None:
    if not (settings.smtp_host and settings.alert_email_to):
        log.debug("Email not configured; skipping")
        return
    msg = EmailMessage()
    msg["Subject"] = f"[Smart CCTV] {event['rule_name']} - {event['camera_id']}"
    msg["From"] = settings.alert_email_from or settings.smtp_user
    msg["To"] = settings.alert_email_to
    msg.set_content(format_text(event))
    snap = _snapshot_file(event)
    if snap:
        msg.add_attachment(snap.read_bytes(), maintype="image", subtype="jpeg", filename=snap.name)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


def send_sms(event: dict) -> None:
    """MSG91 Flow API. Commercial SMS in India needs a DLT-registered template."""
    if not (settings.msg91_auth_key and settings.msg91_template_id and settings.sms_to):
        log.debug("SMS not configured; skipping")
        return
    payload = {
        "template_id": settings.msg91_template_id,
        "short_url": "0",
        "recipients": [
            {"mobiles": num.strip(), "rule": event["rule_name"][:30], "camera": event["camera_id"][:30]}
            for num in settings.sms_to.split(",")
        ],
    }
    r = httpx.post(
        "https://control.msg91.com/api/v5/flow",
        json=payload,
        headers={"authkey": settings.msg91_auth_key, "content-type": "application/json"},
        timeout=15,
    )
    if r.status_code >= 300:
        log.warning("MSG91 error %s: %s", r.status_code, r.text[:200])


def send_push(event: dict) -> None:
    """Phase 4: Firebase Cloud Messaging for the mobile app.

    TODO: store device tokens (POST /api/devices) and send with firebase-admin.
    Until then the web dashboard shows browser notifications via the WebSocket channel.
    """
    log.debug("Push channel not implemented yet (Phase 4)")


CHANNELS = {
    "websocket": send_websocket,
    "telegram": send_telegram,
    "email": send_email,
    "sms": send_sms,
    "push": send_push,
}
