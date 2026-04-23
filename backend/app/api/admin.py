from __future__ import annotations

import asyncio
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ScrapeLog
from ..schemas import ScrapeLogOut
from ..services.sync import run_sync
from ..services.alerts import run_closing_reminders

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/scrape/trigger")
async def trigger_scrape():
    # Fire-and-forget so the HTTP call returns promptly even on long scrapes.
    asyncio.create_task(run_sync())
    return {"status": "started"}


@router.post("/reminders/run")
def trigger_reminders():
    sent = run_closing_reminders()
    return {"status": "ok", "sent": sent}


@router.get("/scrape/logs", response_model=list[ScrapeLogOut])
def scrape_logs(db: Session = Depends(get_db), limit: int = 20):
    rows = db.query(ScrapeLog).order_by(ScrapeLog.started_at.desc()).limit(limit).all()
    return [ScrapeLogOut.model_validate(r) for r in rows]
