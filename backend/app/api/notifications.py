from __future__ import annotations

from datetime import datetime, date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import NotificationRule, Notification
from ..models.notification import NotificationType
from ..schemas import (
    NotificationRuleIn, NotificationRuleOut, NotificationOut, NotificationListResponse,
)
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


@router.get("/notifications/search", response_model=NotificationListResponse)
def search_notifications(
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user_id),
    type: Optional[NotificationType] = None,
    read_status: Optional[str] = None,
    q: Optional[str] = None,
    document_no: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
):
    query = db.query(Notification).filter(Notification.user_id == user_id)

    if type:
        query = query.filter(Notification.type == type)
    if read_status:
        rs = read_status.lower()
        if rs == "unread":
            query = query.filter(Notification.read_at.is_(None))
        elif rs == "read":
            query = query.filter(Notification.read_at.is_not(None))
    if document_no:
        query = query.filter(Notification.document_no == document_no)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Notification.title.ilike(like),
            Notification.body.ilike(like),
            Notification.document_no.ilike(like),
        ))
    if date_from:
        query = query.filter(Notification.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(Notification.created_at <= datetime.combine(date_to, datetime.max.time()))

    total = query.with_entities(func.count(Notification.id)).scalar() or 0
    rows = (
        query.order_by(Notification.created_at.desc())
        .offset((page - 1) * size).limit(size).all()
    )
    items = [NotificationOut.model_validate(n) for n in rows]
    return NotificationListResponse(total=total, page=page, size=size, items=items)


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
