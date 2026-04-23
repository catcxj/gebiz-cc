from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Opportunity, OpportunityStatus, NotificationRule, NotificationType, Watch
from ..notifications import dispatch, NotificationPayload

log = logging.getLogger(__name__)


def match_keywords(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return False
    t = (text or "").lower()
    return any(k.strip().lower() in t for k in keywords if k.strip())


def list_users_with_rules(db: Session) -> Iterable[tuple[str, NotificationRule]]:
    for rule in db.query(NotificationRule).all():
        yield rule.user_id, rule


def run_closing_reminders() -> int:
    """
    For each watched Opportunity in Open status, if its closing_at falls into
    any configured countdown day (N days from today), send a reminder.

    We trigger once per (document_no, user_id, countdown_day) by recording a
    deterministic payload key in the Notification table and checking for
    duplicates.
    """
    db: Session = SessionLocal()
    sent = 0
    try:
        now = datetime.utcnow()
        watches = db.query(Watch).all()
        for w in watches:
            opp = db.get(Opportunity, w.document_no)
            if opp is None or opp.status != OpportunityStatus.Open or opp.closing_at is None:
                continue
            rule = db.query(NotificationRule).filter(NotificationRule.user_id == w.user_id).one_or_none()
            days_list: list[int] = list(rule.countdown_days) if rule else [3, 1]

            delta = opp.closing_at - now
            remaining_days = delta.days
            if remaining_days < 0:
                continue

            # Round fractional day up so a closing "in 0.8 days" still triggers the 1-day rule.
            remaining_days_rounded = remaining_days if delta.seconds == 0 else remaining_days + (1 if delta.seconds > 0 else 0)

            for d in days_list:
                if remaining_days_rounded != d:
                    continue
                if _already_reminded(db, w.user_id, opp.document_no, d):
                    continue
                dispatch(db, w.user_id, NotificationPayload(
                    type=NotificationType.ClosingSoon,
                    title=f"[截标倒计时 {d}天] {opp.document_no}",
                    body=f"{opp.description} — 截标 {opp.closing_at.strftime('%Y-%m-%d %H:%M')}",
                    document_no=opp.document_no,
                    payload={"countdown_days": d, "closing_at": opp.closing_at.isoformat()},
                ))
                sent += 1
    finally:
        db.close()
    log.info("closing reminders sent=%d", sent)
    return sent


def _already_reminded(db: Session, user_id: str, document_no: str, d: int) -> bool:
    from ..models.notification import Notification

    q = (
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.document_no == document_no,
            Notification.type == NotificationType.ClosingSoon,
        )
    )
    for n in q.all():
        if (n.payload or {}).get("countdown_days") == d:
            return True
    return False
