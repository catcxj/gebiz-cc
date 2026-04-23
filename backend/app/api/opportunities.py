from __future__ import annotations

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Opportunity, Watch, InternalNote, OpportunityType, OpportunityStatus
from ..schemas import (
    OpportunityDetail, OpportunityListItem, OpportunityListResponse,
    InternalNoteIn, InternalNoteOut, StatusUpdateOut,
)
from .deps import current_user_id

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("", response_model=OpportunityListResponse)
def list_opportunities(
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user_id),
    agency: Optional[str] = None,
    type: Optional[OpportunityType] = None,
    status: Optional[OpportunityStatus] = None,
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
    return OpportunityDetail(**d)


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
