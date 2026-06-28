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


def dispatch(db: Session, user_id: str, msg: NotificationPayload, rule: Optional[NotificationRule] = None) -> None:
    """
    Deliver one notification to all configured channels for a user.

    If a specific `rule` is provided, we send via that rule.
    If no specific `rule` is provided (e.g. for StatusChanged or System), we aggregate
    all active rules' settings to send to in-app/email/webhook destinations.
    """
    if rule is None:
        rules = db.query(NotificationRule).filter(
            NotificationRule.user_id == user_id,
            NotificationRule.is_active == True
        ).all()
        
        # If there are no active rules, default to in-app only
        if not rules:
            db.add(Notification(
                user_id=user_id,
                type=msg.type,
                title=msg.title,
                body=msg.body,
                document_no=msg.document_no,
                payload=msg.payload,
            ))
            db.commit()
            return

        if any(r.channel_in_app for r in rules):
            db.add(Notification(
                user_id=user_id,
                type=msg.type,
                title=msg.title,
                body=msg.body,
                document_no=msg.document_no,
                payload=msg.payload,
            ))
            db.commit()

        # Deduplicated emails
        emails = {r.email_to.strip() for r in rules if r.channel_email and r.email_to and r.email_to.strip()}
        for email in emails:
            try:
                EmailChannel(email).send(msg.title, msg.body, msg.payload)
            except Exception:
                log.exception("email channel failed")

        # Deduplicated webhooks: map URL to the first active rule's keyword
        webhooks = {}
        for r in rules:
            if r.channel_webhook and r.webhook_url and r.webhook_url.strip():
                url = r.webhook_url.strip()
                if url not in webhooks:
                    webhooks[url] = r.webhook_keyword
        for url, keyword in webhooks.items():
            try:
                WebhookChannel(url, keyword).send(msg.title, msg.body, msg.payload)
            except Exception:
                log.exception("webhook channel failed")
    else:
        # Send using the specific rule
        if rule.channel_in_app:
            # Inject rule name and rule ID into payload for grouping and frontend rendering
            payload = dict(msg.payload or {})
            payload["rule_name"] = rule.name
            payload["rule_id"] = rule.id

            db.add(Notification(
                user_id=user_id,
                type=msg.type,
                title=msg.title,
                body=msg.body,
                document_no=msg.document_no,
                payload=payload,
            ))
            db.commit()

        if rule.channel_email and rule.email_to:
            try:
                EmailChannel(rule.email_to).send(msg.title, msg.body, msg.payload)
            except Exception:
                log.exception("email channel failed")

        if rule.channel_webhook and rule.webhook_url:
            try:
                WebhookChannel(rule.webhook_url, rule.webhook_keyword).send(msg.title, msg.body, msg.payload)
            except Exception:
                log.exception("webhook channel failed")
