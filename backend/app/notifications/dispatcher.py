from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from ..models.notification import NotificationRule, Notification, NotificationType
from .channels import EmailChannel, WebhookChannel

log = logging.getLogger(__name__)


@dataclass
class NotificationPayload:
    type: NotificationType
    title: str
    body: str
    document_no: Optional[str] = None
    payload: Optional[dict] = None


def dispatch(db: Session, user_id: str, msg: NotificationPayload) -> None:
    """
    Deliver one notification to all configured channels for a user.

    In-app messages are persisted as Notification rows so the UI message
    center can list them. Email/webhook are best-effort (exceptions are
    logged, not propagated — a single channel failure must not block others).
    """
    rule = db.query(NotificationRule).filter(NotificationRule.user_id == user_id).one_or_none()

    if rule is None or rule.channel_in_app:
        db.add(Notification(
            user_id=user_id,
            type=msg.type,
            title=msg.title,
            body=msg.body,
            document_no=msg.document_no,
            payload=msg.payload,
        ))
        db.commit()

    if rule is None:
        return

    if rule.channel_email and rule.email_to:
        try:
            EmailChannel(rule.email_to).send(msg.title, msg.body, msg.payload)
        except Exception:
            log.exception("email channel failed")

    if rule.channel_webhook and rule.webhook_url:
        try:
            WebhookChannel(rule.webhook_url).send(msg.title, msg.body, msg.payload)
        except Exception:
            log.exception("webhook channel failed")
