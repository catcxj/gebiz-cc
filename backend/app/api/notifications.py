from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import NotificationRule, Notification
from ..schemas import NotificationRuleIn, NotificationRuleOut, NotificationOut
from .deps import current_user_id

router = APIRouter(tags=["notifications"])


@router.get("/notification-rules", response_model=list[NotificationRuleOut])
def list_rules(db: Session = Depends(get_db), user_id: str = Depends(current_user_id)):
    rules = db.query(NotificationRule).filter(NotificationRule.user_id == user_id).all()
    if not rules:
        rule = NotificationRule(
            user_id=user_id,
            name="默认规则",
            is_active=True,
            keywords=[],
            agencies=[],
            categories=[],
            countdown_days=[3, 1]
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        rules = [rule]
    return [NotificationRuleOut.model_validate(r) for r in rules]


@router.post("/notification-rules", response_model=NotificationRuleOut)
def create_rule(body: NotificationRuleIn, db: Session = Depends(get_db), user_id: str = Depends(current_user_id)):
    rule = NotificationRule(
        user_id=user_id,
        name=body.name,
        is_active=body.is_active,
        keywords=body.keywords,
        agencies=body.agencies,
        categories=body.categories,
        countdown_days=body.countdown_days,
        channel_in_app=body.channel_in_app,
        channel_email=body.channel_email,
        email_to=body.email_to,
        channel_webhook=body.channel_webhook,
        webhook_url=body.webhook_url
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return NotificationRuleOut.model_validate(rule)


@router.put("/notification-rules/{rule_id}", response_model=NotificationRuleOut)
def put_rule(rule_id: int, body: NotificationRuleIn, db: Session = Depends(get_db), user_id: str = Depends(current_user_id)):
    rule = db.query(NotificationRule).filter(NotificationRule.id == rule_id, NotificationRule.user_id == user_id).one_or_none()
    if rule is None:
        raise HTTPException(404, "Notification rule not found")
    rule.name = body.name
    rule.is_active = body.is_active
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


@router.delete("/notification-rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db), user_id: str = Depends(current_user_id)):
    rule = db.query(NotificationRule).filter(NotificationRule.id == rule_id, NotificationRule.user_id == user_id).one_or_none()
    if rule is None:
        raise HTTPException(404, "Notification rule not found")
    db.delete(rule)
    db.commit()
    return None


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
