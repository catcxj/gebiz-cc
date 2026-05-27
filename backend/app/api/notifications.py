from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import NotificationRule, Notification
from ..schemas import NotificationRuleIn, NotificationRuleOut, NotificationOut
from .deps import current_user_id

router = APIRouter(tags=["notifications"])


@router.get("/notification-rules", response_model=NotificationRuleOut)
def get_rule(db: Session = Depends(get_db), user_id: str = Depends(current_user_id)):
    rule = db.query(NotificationRule).filter(NotificationRule.user_id == user_id).one_or_none()
    if rule is None:
        rule = NotificationRule(user_id=user_id, keywords=[], agencies=[], categories=[], countdown_days=[3, 1])
        db.add(rule)
        db.commit()
        db.refresh(rule)
    return NotificationRuleOut.model_validate(rule)


@router.put("/notification-rules", response_model=NotificationRuleOut)
def put_rule(body: NotificationRuleIn, db: Session = Depends(get_db), user_id: str = Depends(current_user_id)):
    rule = db.query(NotificationRule).filter(NotificationRule.user_id == user_id).one_or_none()
    if rule is None:
        rule = NotificationRule(user_id=user_id)
        db.add(rule)
    rule.keywords = body.keywords
    rule.agencies = body.agencies
    rule.categories = body.categories
    rule.countdown_days = body.countdown_days
    rule.channel_in_app = body.channel_in_app
    rule.channel_email = body.channel_email
    rule.email_to = body.email_to
    rule.channel_webhook = body.channel_webhook
    rule.webhook_url = body.webhook_url
    db.commit()
    db.refresh(rule)
    return NotificationRuleOut.model_validate(rule)


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user_id),
    unread_only: bool = False,
    limit: int = 50,
):
    q = db.query(Notification).filter(Notification.user_id == user_id)
    if unread_only:
        q = q.filter(Notification.read_at.is_(None))
    return [NotificationOut.model_validate(n) for n in q.order_by(Notification.created_at.desc()).limit(limit).all()]


@router.patch("/notifications/{nid}/read", status_code=204)
def mark_read(nid: int, db: Session = Depends(get_db), user_id: str = Depends(current_user_id)):
    n = db.query(Notification).filter(Notification.id == nid, Notification.user_id == user_id).one_or_none()
    if n is None:
        raise HTTPException(404, "not found")
    if n.read_at is None:
        n.read_at = datetime.utcnow()
        db.commit()


@router.post("/notifications/read-all", status_code=204)
def mark_all_read(db: Session = Depends(get_db), user_id: str = Depends(current_user_id)):
    db.query(Notification).filter(
        Notification.user_id == user_id, Notification.read_at.is_(None)
    ).update({Notification.read_at: datetime.utcnow()}, synchronize_session=False)
    db.commit()
