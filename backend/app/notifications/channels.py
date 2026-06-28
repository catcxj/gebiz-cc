from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

import httpx

from ..config import settings

log = logging.getLogger(__name__)


class Channel(Protocol):
    name: str

    def send(self, title: str, body: str, payload: dict | None = None) -> None: ...


class InAppChannel:
    """Persisted via NotificationService; this is a no-op for the dispatcher."""
    name = "in_app"

    def send(self, title, body, payload=None):
        return


class EmailChannel:
    name = "email"

    def __init__(self, to: str):
        self.to = to

    def send(self, title, body, payload=None):
        if not settings.smtp_host or not settings.smtp_from:
            log.warning("email channel skipped: SMTP not configured")
            return
        msg = EmailMessage()
        msg["Subject"] = title
        msg["From"] = settings.smtp_from
        msg["To"] = self.to
        msg.set_content(body or "")
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
            smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_pass or "")
            smtp.send_message(msg)


class WebhookChannel:
    """
    Generic webhook: posts JSON to any URL. Users point this at their
    WeCom / Feishu / Slack incoming-webhook endpoint. We post a minimal
    body — complex channel-specific formatting is out of scope.
    """
    name = "webhook"

    def __init__(self, url: str, keyword: str | None = None):
        self.url = url
        self.keyword = keyword

    def send(self, title, body, payload=None):
        # Prepend keyword to text/title so it passes security keyword verification checks (e.g. for Feishu / WeCom)
        full_title = f"[{self.keyword}] {title}" if self.keyword else title
        full_text = f"{self.keyword}\n{title}\n{body}" if self.keyword else f"{title}\n{body}"

        try:
            httpx.post(
                self.url,
                json={
                    "title": full_title,
                    "text": body,
                    "keyword": self.keyword,
                    "payload": payload or {},
                    "msg_type": "text",
                    "content": {"text": full_text},
                },
                timeout=10,
            )
        except Exception as exc:
            log.exception("webhook send failed: %s", exc)
