"""Application settings, read from environment variables / .env file."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

# .env at project root (preferred) or inside backend/
load_dotenv(PROJECT_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(os.getenv("DATA_DIR", BACKEND_DIR / "data")).resolve()
        self.snapshot_dir = self.data_dir / "snapshots"
        self.database_url = os.getenv("DATABASE_URL", f"sqlite:///{self.data_dir / 'smart_cctv.db'}")
        self.cameras_file = Path(os.getenv("CAMERAS_FILE", BACKEND_DIR / "config" / "cameras.yaml"))
        self.rules_file = Path(os.getenv("RULES_FILE", BACKEND_DIR / "config" / "rules.yaml"))

        # Detection
        self.detector = os.getenv("DETECTOR", "yolo")  # yolo | mock
        self.yolo_model = os.getenv("YOLO_MODEL", "yolo11n.pt")
        self.device = os.getenv("DEVICE", "auto")  # auto | cpu | mps | cuda
        self.confidence = float(os.getenv("DETECTION_CONFIDENCE", "0.4"))
        self.plate_ocr = _bool("PLATE_OCR")
        # seconds between full-frame text/number reads (only while a rule with text_pattern is on)
        self.text_ocr_interval = float(os.getenv("TEXT_OCR_INTERVAL", "1.5"))
        self.embeddings = _bool("EMBEDDINGS")

        # Alerts
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.smtp_host = os.getenv("SMTP_HOST", "")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.alert_email_from = os.getenv("ALERT_EMAIL_FROM", self.smtp_user)
        self.alert_email_to = os.getenv("ALERT_EMAIL_TO", "")
        self.msg91_auth_key = os.getenv("MSG91_AUTH_KEY", "")
        self.msg91_template_id = os.getenv("MSG91_TEMPLATE_ID", "")
        self.sms_to = os.getenv("SMS_TO", "")
        self.public_base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")

        # Prompt search / AI
        self.llm_provider = os.getenv("LLM_PROVIDER", "none")  # none | anthropic | ollama
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5vl:7b")

        # Web
        self.cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
