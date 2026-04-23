from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Opportunity, StatusUpdate, ScrapeLog, NotificationType, Watch
from ..notifications import dispatch, NotificationPayload
from ..scrapers import ScrapedOpportunity, get_scraper
from .alerts import match_keywords, list_users_with_rules

log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    new: int
    updated: int
    status_changes: int


async def run_sync() -> SyncResult:
    """
    One scrape run: fetch all items, upsert, diff status, emit notifications.
    """
    db: Session = SessionLocal()
    log_row = ScrapeLog(started_at=datetime.utcnow(), status="running")
    db.add(log_row)
    db.commit()
    db.refresh(log_row)

    new = updated = changes = 0
    try:
        scraper = get_scraper()
        async for item in scraper.fetch():
            created, status_changed = _upsert(db, item)
            if created:
                new += 1
                _notify_if_match(db, item)
            else:
                updated += 1
                if status_changed:
                    changes += 1
                    _notify_status_changed(db, item)
        db.commit()
        log_row.items_new = new
        log_row.items_updated = updated
        log_row.status = "ok"
    except Exception as exc:
        log.exception("sync failed")
        db.rollback()
        log_row.status = "failed"
        log_row.error = str(exc)[:2000]
        _alert_admins(db, f"GeBIZ scrape failed: {exc}")
    finally:
        log_row.finished_at = datetime.utcnow()
        db.add(log_row)
        db.commit()
        db.close()

    log.info("sync done: new=%d updated=%d status_changes=%d", new, updated, changes)
    return SyncResult(new=new, updated=updated, status_changes=changes)


def _upsert(db: Session, item: ScrapedOpportunity) -> tuple[bool, bool]:
    existing = db.get(Opportunity, item.document_no)
    if existing is None:
        db.add(Opportunity(
            document_no=item.document_no,
            opportunity_type=item.opportunity_type,
            description=item.description,
            agency=item.agency,
            published_date=item.published_date,
            closing_at=item.closing_at,
            status=item.status,
            procurement_category=item.procurement_category,
            contact_person=item.contact_person,
            award_details=item.award_details,
            source_url=item.source_url,
        ))
        return True, False

    status_changed = existing.status != item.status
    if status_changed:
        db.add(StatusUpdate(
            document_no=existing.document_no,
            from_status=existing.status,
            to_status=item.status,
        ))

    existing.opportunity_type = item.opportunity_type or existing.opportunity_type
    existing.description = item.description or existing.description
    existing.agency = item.agency or existing.agency
    existing.published_date = item.published_date or existing.published_date
    existing.closing_at = item.closing_at or existing.closing_at
    existing.status = item.status
    existing.procurement_category = item.procurement_category or existing.procurement_category
    existing.contact_person = item.contact_person or existing.contact_person
    existing.award_details = item.award_details or existing.award_details
    existing.source_url = item.source_url or existing.source_url
    return False, status_changed


def _notify_if_match(db: Session, item: ScrapedOpportunity) -> None:
    for user_id, rule in list_users_with_rules(db):
        if match_keywords(item.description, rule.keywords) or match_keywords(item.agency or "", rule.keywords):
            dispatch(db, user_id, NotificationPayload(
                type=NotificationType.NewMatch,
                title=f"[新商机] {item.document_no}",
                body=f"{item.agency or ''} — {item.description}",
                document_no=item.document_no,
                payload={"agency": item.agency, "closing_at": item.closing_at.isoformat() if item.closing_at else None},
            ))


def _notify_status_changed(db: Session, item: ScrapedOpportunity) -> None:
    # Only notify watchers — non-watchers get no noise.
    watchers = db.query(Watch).filter(Watch.document_no == item.document_no).all()
    for w in watchers:
        dispatch(db, w.user_id, NotificationPayload(
            type=NotificationType.StatusChanged,
            title=f"[状态变更] {item.document_no} → {item.status.value}",
            body=f"{item.description}",
            document_no=item.document_no,
            payload={"new_status": item.status.value},
        ))


def _alert_admins(db: Session, text: str) -> None:
    """Dispatch a system alert to everyone who has a rule (crude but adequate)."""
    for user_id, _rule in list_users_with_rules(db):
        dispatch(db, user_id, NotificationPayload(
            type=NotificationType.System,
            title="[系统告警] 抓取失败",
            body=text,
        ))
