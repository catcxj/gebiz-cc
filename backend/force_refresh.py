import asyncio
import logging
import sys
from pathlib import Path

# Add backend root to path
sys.path.append(str(Path(__file__).parent))

from app.database import SessionLocal
from app.models import Opportunity
from app.scrapers import get_scraper
from app.services.sync import _upsert, _notify_status_changed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
)

log = logging.getLogger("force_refresh")

async def main():
    db = SessionLocal()
    try:
        # Get all opportunities from database
        opps = db.query(Opportunity).all()
        log.info(f"Found {len(opps)} opportunities in database.")
        
        scraper = get_scraper()
        log.info(f"Using scraper: {scraper.__class__.__name__}")
        
        success_count = 0
        status_changes = 0
        
        for idx, opp in enumerate(opps):
            log.info(f"[{idx+1}/{len(opps)}] Enriching opportunity: {opp.document_no} (Current Status: {opp.status.value})")
            try:
                enriched = await scraper.enrich_opportunity(opp.document_no)
                if enriched:
                    # Perform upsert and check if status changed
                    _, status_changed = _upsert(db, enriched)
                    db.commit()
                    success_count += 1
                    if status_changed:
                        status_changes += 1
                        log.info(f"Status changed for {opp.document_no} -> {enriched.status.value}")
                        _notify_status_changed(db, enriched)
                else:
                    log.warning(f"Could not enrich opportunity: {opp.document_no} (no data returned)")
            except Exception as e:
                db.rollback()
                log.exception(f"Failed to enrich opportunity: {opp.document_no}")
                
        log.info(f"Force refresh finished: {success_count}/{len(opps)} enriched successfully. Status changes detected: {status_changes}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
