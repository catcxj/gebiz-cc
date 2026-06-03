import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Add backend root to path
sys.path.append(str(Path(__file__).parent))

from app.database import SessionLocal
from app.models import Opportunity, StatusUpdate, OpportunityStatus

def main():
    db = SessionLocal()
    sg_now = (datetime.now(timezone.utc) + timedelta(hours=8)).replace(tzinfo=None)
    print(f"Current Singapore Time (SGT): {sg_now}")
    
    # Query using the underlying _status column to find opportunities stored as 'Open' in DB but expired
    expired_opps = (
        db.query(Opportunity)
        .filter(
            Opportunity._status == OpportunityStatus.Open,
            Opportunity.closing_at.isnot(None),
            Opportunity.closing_at < sg_now
        )
        .all()
    )
    
    total = len(expired_opps)
    print(f"Found {total} expired 'Open' opportunities to update in database.")
    
    if total == 0:
        print("No opportunities need updating.")
        db.close()
        return

    updated_count = 0
    for opp in expired_opps:
        # Record status update log
        status_update = StatusUpdate(
            document_no=opp.document_no,
            from_status=OpportunityStatus.Open,
            to_status=OpportunityStatus.Closed,
            note="Automatically marked as Closed because closing time has passed."
        )
        db.add(status_update)
        
        # Set database status to Closed
        opp.status = OpportunityStatus.Closed
        updated_count += 1
        print(f"[{updated_count}/{total}] Updated {opp.document_no} (Closed on: {opp.closing_at})")
        
    db.commit()
    print(f"Successfully updated and committed {updated_count} opportunities in the database.")
    db.close()

if __name__ == "__main__":
    main()
