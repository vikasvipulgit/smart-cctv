"""Sends each event to every channel its rule lists, without blocking the video pipeline."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from .channels import CHANNELS

log = logging.getLogger(__name__)


class AlertDispatcher:
    def __init__(self, max_workers: int = 4) -> None:
        self.pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="alert")

    def dispatch(self, event: dict, channels: list[str]) -> None:
        for name in channels:
            fn = CHANNELS.get(name)
            if fn is None:
                log.warning("Unknown alert channel %r", name)
                continue
            self.pool.submit(self._safe, name, fn, event)

    @staticmethod
    def _safe(name, fn, event) -> None:
        try:
            fn(event)
        except Exception as exc:
            log.warning("Alert channel %s failed: %s", name, exc)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)


dispatcher = AlertDispatcher()
