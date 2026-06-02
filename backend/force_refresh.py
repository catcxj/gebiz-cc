import asyncio
import logging
import random
import sys
from pathlib import Path

# Add backend root to path
sys.path.append(str(Path(__file__).parent))

from app.database import SessionLocal
from app.models import Opportunity
from app.scrapers import get_scraper
from app.services.sync import _upsert, _notify_status_changed

# Configurations for human-like scraping behavior and anti-scanning detection
BATCH_SIZE = 10              # Number of items per batch
DELAY_MIN = 3.0              # Minimum delay (seconds) between individual requests
DELAY_MAX = 7.0              # Maximum delay (seconds) between individual requests
BATCH_DELAY_MIN = 30.0       # Minimum delay (seconds) between batches
BATCH_DELAY_MAX = 60.0       # Maximum delay (seconds) between batches

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
        total_opps = len(opps)
        log.info(f"Found {total_opps} opportunities in database.")
        
        scraper = get_scraper()
        log.info(f"Using scraper: {scraper.__class__.__name__}")
        log.info(
            f"Throttling Plan: Batch size = {BATCH_SIZE}. "
            f"Item delay = {DELAY_MIN}-{DELAY_MAX}s. "
            f"Batch delay = {BATCH_DELAY_MIN}-{BATCH_DELAY_MAX}s."
        )
        
        success_count = 0
        status_changes = 0
        
        for idx, opp in enumerate(opps):
            # Check if we need to sleep before processing
            if idx > 0:
                if idx % BATCH_SIZE == 0:
                    batch_sleep = random.uniform(BATCH_DELAY_MIN, BATCH_DELAY_MAX)
                    log.info(f"Finished batch. Sleeping for {batch_sleep:.2f}s before starting next batch...")
                    await asyncio.sleep(batch_sleep)
                else:
                    item_sleep = random.uniform(DELAY_MIN, DELAY_MAX)
                    log.info(f"Sleeping for {item_sleep:.2f}s before next request to prevent scanning alerts...")
                    await asyncio.sleep(item_sleep)

            log.info(f"[{idx+1}/{total_opps}] Enriching opportunity: {opp.document_no} (Current Status: {opp.status.value})")
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
                
        log.info(f"Force refresh finished: {success_count}/{total_opps} enriched successfully. Status changes detected: {status_changes}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
