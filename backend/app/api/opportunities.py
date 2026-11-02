from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, func, case
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Opportunity, Watch, InternalNote, OpportunityType, OpportunityStatus, OpportunityRespondent
from ..schemas import (
    OpportunityDetail, OpportunityListItem, OpportunityListResponse, OpportunityFetchResult,
    InternalNoteIn, InternalNoteOut, StatusUpdateOut,
    OpportunityRespondentOut, SupplierOut, SupplierDetailOut, SupplierDetailOpportunity
)
from .deps import current_user_id
from ..services.sync import fetch_opportunity_by_doc_no

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("", response_model=OpportunityListResponse)
def list_opportunities(
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user_id),
    agency: Optional[str] = None,
    type: Optional[OpportunityType] = None,
    status: Optional[OpportunityStatus] = None,
    source: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    q: Optional[str] = None,
    watched_only: bool = False,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    query = db.query(Opportunity)

    if agency:
        query = query.filter(Opportunity.agency == agency)
    if type:
        query = query.filter(Opportunity.opportunity_type == type)
    if status:
        query = query.filter(Opportunity.status == status)
    if source:
        if source.lower() == "psa":
            query = query.filter(Opportunity.agency == "PSA")
        elif source.lower() == "gebiz":
            query = query.filter(or_(Opportunity.agency != "PSA", Opportunity.agency.is_(None)))
    if date_from:
        query = query.filter(Opportunity.published_date >= date_from)
    if date_to:
        query = query.filter(Opportunity.published_date <= date_to)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Opportunity.description.ilike(like), Opportunity.document_no.ilike(like)))
    if watched_only:
        query = query.join(Watch, Watch.document_no == Opportunity.document_no).filter(Watch.user_id == user_id)

    total = query.with_entities(func.count(Opportunity.document_no)).scalar() or 0
    rows = (
        query.order_by(Opportunity.published_date.desc().nullslast(), Opportunity.document_no.desc())
        .offset((page - 1) * size).limit(size).all()
    )

    if rows:
        doc_nos = [o.document_no for o in rows]
        watched = {
            w.document_no for w in db.query(Watch).filter(
                Watch.user_id == user_id,
                Watch.document_no.in_(doc_nos),
            ).all()
        }
    else:
        watched = set()

    items = []
    for r in rows:
        d = OpportunityListItem.model_validate(r).model_dump()
        d["is_watched"] = r.document_no in watched
        items.append(OpportunityListItem(**d))

    return OpportunityListResponse(total=total, page=page, size=size, items=items)


@router.get("/{document_no}", response_model=OpportunityDetail)
def get_opportunity(document_no: str, db: Session = Depends(get_db), user_id: str = Depends(current_user_id)):
    opp = db.get(Opportunity, document_no)
    if opp is None:
        raise HTTPException(404, "not found")
    is_watched = db.query(Watch).filter(Watch.document_no == document_no, Watch.user_id == user_id).count() > 0
    d = OpportunityDetail.model_validate(opp).model_dump()
    d["is_watched"] = is_watched
    d["status_updates"] = [StatusUpdateOut.model_validate(s).model_dump() for s in opp.status_updates]
    d["notes"] = [InternalNoteOut.model_validate(n).model_dump() for n in opp.notes]
    d["respondents"] = [OpportunityRespondentOut.model_validate(r).model_dump() for r in opp.respondents]
    return OpportunityDetail(**d)


@router.post("/{document_no}/fetch", response_model=OpportunityFetchResult)
async def fetch_opportunity(
    document_no: str,
    force: bool = False,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user_id),
):
    """
    Given a specific DOC No.: if it does not exist in the database yet,
    add it and scrape its data from the source site. If it already exists,
    return it as-is, unless force=true is passed, in which case it is
    re-scraped and updated.
    """
    doc_no = (document_no or "").strip()
    if not doc_no:
        raise HTTPException(400, "document_no is required")
    try:
        opp, created = await fetch_opportunity_by_doc_no(db, doc_no, force=force)
    except Exception as exc:
        raise HTTPException(502, f"scrape failed: {exc}")
    if opp is None:
        raise HTTPException(404, f"document {doc_no} not found on source site")

    d = OpportunityDetail.model_validate(opp).model_dump()
    d["is_watched"] = db.query(Watch).filter(Watch.document_no == doc_no, Watch.user_id == user_id).count() > 0
    d["status_updates"] = [StatusUpdateOut.model_validate(s).model_dump() for s in opp.status_updates]
    d["notes"] = [InternalNoteOut.model_validate(n).model_dump() for n in opp.notes]
    d["respondents"] = [OpportunityRespondentOut.model_validate(r).model_dump() for r in opp.respondents]
    return OpportunityFetchResult(
        created=created,
        message=(
            "added and scraped from source" if created
            else "refreshed from source" if force
            else "already exists in database"
        ),
        opportunity=OpportunityDetail(**d),
    )


@router.post("/{document_no}/watch", status_code=204)
def watch(document_no: str, db: Session = Depends(get_db), user_id: str = Depends(current_user_id)):
    if db.get(Opportunity, document_no) is None:
        raise HTTPException(404, "not found")
    existing = db.query(Watch).filter(Watch.document_no == document_no, Watch.user_id == user_id).one_or_none()
    if existing is None:
        db.add(Watch(document_no=document_no, user_id=user_id))
        db.commit()


@router.delete("/{document_no}/watch", status_code=204)
def unwatch(document_no: str, db: Session = Depends(get_db), user_id: str = Depends(current_user_id)):
    db.query(Watch).filter(Watch.document_no == document_no, Watch.user_id == user_id).delete()
    db.commit()


@router.post("/{document_no}/notes", response_model=InternalNoteOut)
def add_note(document_no: str, body: InternalNoteIn, db: Session = Depends(get_db), user_id: str = Depends(current_user_id)):
    if db.get(Opportunity, document_no) is None:
        raise HTTPException(404, "not found")
    note = InternalNote(document_no=document_no, author=body.author or user_id, content=body.content)
    db.add(note)
    db.commit()
    db.refresh(note)
    return InternalNoteOut.model_validate(note)


@router.get("/meta/agencies", response_model=list[str])
def list_agencies(db: Session = Depends(get_db)):
    rows = db.query(Opportunity.agency).filter(Opportunity.agency.isnot(None)).distinct().all()
    return sorted(r[0] for r in rows)


def _supplier_key(name: str | None) -> str:
    return (name or "").strip().lower()


def _awarded_amount_from_details(
    opp: Opportunity,
    supplier_name: str,
    awarded_counts: Counter | None = None,
) -> float | None:
    """
    Return the amount actually awarded to this supplier, taken from the Award
    tab snapshot. Returns None when the amount is not known.
    """
    details = opp.award_details or {}
    awardees = details.get("awardees")

    if isinstance(awardees, list) and awardees:
        key = _supplier_key(supplier_name)
        for awardee in awardees:
            if _supplier_key(awardee.get("supplier_name")) == key:
                amount = awardee.get("amount")
                try:
                    return float(amount) if amount is not None else None
                except (TypeError, ValueError):
                    return None
        return None

    # Legacy single-awardee snapshot. Before multi-award support, a
    # multi-award page stored the TOTAL under the first supplier, so it must
    # not be attributed to that supplier when several were awarded.
    if awarded_counts is not None and awarded_counts.get(opp.document_no, 0) > 1:
        return None
    if _supplier_key(details.get("supplier_name")) == _supplier_key(supplier_name):
        amount = details.get("amount")
        try:
            return float(amount) if amount is not None else None
        except (TypeError, ValueError):
            return None
    return None


@router.get("/meta/suppliers", response_model=list[SupplierOut])
def list_suppliers(q: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(
        OpportunityRespondent.supplier_name,
        func.count(OpportunityRespondent.id).label("total_bids"),
        func.sum(case((OpportunityRespondent.is_awarded == True, 1), else_=0)).label("total_awards"),
    ).group_by(OpportunityRespondent.supplier_name)

    if q:
        query = query.filter(OpportunityRespondent.supplier_name.ilike(f"%{q}%"))

    rows = query.order_by(
        func.sum(case((OpportunityRespondent.is_awarded == True, 1), else_=0)).desc(),
        OpportunityRespondent.supplier_name
    ).all()

    # Awarded amounts live in the Award-tab snapshot (award_details.awardees),
    # not in the bid amount stored on the respondent row.
    awarded_rows = (
        db.query(OpportunityRespondent, Opportunity)
        .join(Opportunity, Opportunity.document_no == OpportunityRespondent.document_no)
        .filter(OpportunityRespondent.is_awarded == True)
        .all()
    )
    awarded_counts = Counter(resp.document_no for resp, _ in awarded_rows)
    awarded_totals: dict[str, float] = defaultdict(float)
    for resp, opp in awarded_rows:
        amount = _awarded_amount_from_details(opp, resp.supplier_name, awarded_counts)
        if amount is not None:
            awarded_totals[resp.supplier_name] += amount

    suppliers = []
    for r in rows:
        suppliers.append(SupplierOut(
            supplier_name=r.supplier_name,
            total_bids=r.total_bids or 0,
            total_awards=r.total_awards or 0,
            total_award_amount=awarded_totals.get(r.supplier_name, 0.0),
        ))
    return suppliers


@router.get("/meta/suppliers/{name}", response_model=SupplierDetailOut)
def get_supplier(name: str, db: Session = Depends(get_db)):
    resps = db.query(OpportunityRespondent).filter(OpportunityRespondent.supplier_name == name).all()
    if not resps:
        raise HTTPException(404, "Supplier not found")

    doc_nos = [r.document_no for r in resps]
    awarded_counts = Counter(
        doc for (doc,) in db.query(OpportunityRespondent.document_no)
        .filter(
            OpportunityRespondent.is_awarded == True,
            OpportunityRespondent.document_no.in_(doc_nos),
        ).all()
    )

    bids = []
    total_bids = len(resps)
    total_awards = 0
    total_award_amount = 0.0

    for r in resps:
        opp = r.opportunity
        awarded_amount = None
        if r.is_awarded:
            total_awards += 1
            awarded_amount = _awarded_amount_from_details(opp, r.supplier_name, awarded_counts)
            if awarded_amount is not None:
                total_award_amount += awarded_amount

        bids.append(SupplierDetailOpportunity(
            document_no=opp.document_no,
            description=opp.description,
            status=opp.status,
            published_date=opp.published_date,
            amount=r.amount,
            awarded_amount=awarded_amount,
            is_awarded=r.is_awarded,
        ))

    return SupplierDetailOut(
        supplier_name=name,
        total_bids=total_bids,
        total_awards=total_awards,
        total_award_amount=total_award_amount,
        bids=bids
    )
