from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Opportunity, StatusUpdate, ScrapeLog, NotificationType, Watch, OpportunityStatus, OpportunityRespondent
from ..notifications import dispatch, NotificationPayload
from ..scrapers import ScrapedOpportunity, get_scrapers, get_scraper_for_opp
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
    Then enrich active opportunities in the database.
    """
    db: Session = SessionLocal()
    log_row = ScrapeLog(started_at=datetime.utcnow(), status="running")
    db.add(log_row)
    db.commit()
    db.refresh(log_row)

    new = updated = changes = 0
    try:
        # Get existing opportunity IDs from db to enable smart stopping in pagination
        existing_ids = {r[0] for r in db.query(Opportunity.document_no).all()}

        # 1. Fetch listing and upsert from all scrapers
        scrapers = get_scrapers()
        for scraper in scrapers:
            try:
                async for item in scraper.fetch(existing_ids=existing_ids):
                    created, status_changed = _upsert(db, item)
                    if created:
                        new += 1
                        _notify_if_match(db, item)
                    else:
                        updated += 1
                        if status_changed:
                            changes += 1
                            _notify_status_changed(db, item)
            except Exception as e:
                log.exception("failed to fetch from scraper %s", scraper.__class__.__name__)

        # Commit listing phase results immediately so users see newly scraped list data in the UI
        db.commit()

        # 2. Enrich active/non-final opportunities, plus Awarded opportunities that haven't been enriched yet
        active_opps = db.query(Opportunity).filter(
            or_(
                Opportunity.status.in_([OpportunityStatus.Open, OpportunityStatus.Closed, OpportunityStatus.PendingAward]),
                and_(
                    Opportunity.status == OpportunityStatus.Awarded,
                    Opportunity.award_details.is_(None)
                )
            )
        ).all()
        log.info("sync: enriching %d active opportunities", len(active_opps))
        
        for opp in active_opps:
            try:
                opp_scraper = get_scraper_for_opp(opp)
                enriched = await opp_scraper.enrich_opportunity(opp.document_no)
                if enriched:
                    # If document_no was refined (e.g. from slug to real ref), delete the temporary record
                    if enriched.document_no != opp.document_no:
                        db.delete(opp)
                        db.commit()
                    _, status_changed = _upsert(db, enriched)
                    db.commit() # Commit each enrichment immediately
                    if status_changed:
                        changes += 1
                        _notify_status_changed(db, enriched)
            except Exception:
                db.rollback()
                log.exception("failed to enrich active opportunity %s", opp.document_no)

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
        new_opp = Opportunity(
            document_no=item.document_no,
            reference_no=item.reference_no,
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
        )
        db.add(new_opp)
        
        # Add respondents
        if item.respondents:
            for r in item.respondents:
                db.add(OpportunityRespondent(
                    document_no=item.document_no,
                    supplier_name=r["supplier_name"],
                    amount=r["amount"],
                    is_awarded=r["is_awarded"]
                ))
        return True, False

    status_changed = existing.status != item.status
    if status_changed:
        db.add(StatusUpdate(
            document_no=existing.document_no,
            from_status=existing.status,
            to_status=item.status,
        ))

    existing.reference_no = item.reference_no or existing.reference_no
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
    
    # Update respondents: delete existing and write new ones
    if item.respondents:
        db.query(OpportunityRespondent).filter(OpportunityRespondent.document_no == existing.document_no).delete()
        for r in item.respondents:
            db.add(OpportunityRespondent(
                document_no=existing.document_no,
                supplier_name=r["supplier_name"],
                amount=r["amount"],
                is_awarded=r["is_awarded"]
            ))
    return False, status_changed


def _notify_if_match(db: Session, item: ScrapedOpportunity) -> None:
    for user_id, rule in list_users_with_rules(db):
        rule_keywords = rule.keywords or []
        rule_agencies = getattr(rule, "agencies", []) or []
        rule_categories = getattr(rule, "categories", []) or []

        # If no criteria is configured, do not match anything
        if not rule_keywords and not rule_agencies and not rule_categories:
            continue

        match = True
        
        # 1. Match keywords (description or agency)
        if rule_keywords:
            if not (match_keywords(item.description, rule_keywords) or match_keywords(item.agency or "", rule_keywords)):
                match = False
            
        # 2. Match agencies
        if match and rule_agencies:
            if not item.agency or not any(a.strip().lower() in item.agency.lower() for a in rule_agencies if a.strip()):
                match = False
                
        # 3. Match categories
        if match and rule_categories:
            if not item.procurement_category or not any(c.strip().lower() in item.procurement_category.lower() for c in rule_categories if c.strip()):
                match = False
                
        if match:
            dispatch(db, user_id, NotificationPayload(
                type=NotificationType.NewMatch,
                title=f"[新商机 - {rule.name}] {item.document_no}",
                body=f"{item.agency or ''} — {item.description}",
                document_no=item.document_no,
                payload={"agency": item.agency, "closing_at": item.closing_at.isoformat() if item.closing_at else None},
            ), rule=rule)


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
