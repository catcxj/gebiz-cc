from __future__ import annotations

import random
from datetime import datetime, date, timedelta
from typing import AsyncIterator

from .base import BaseScraper, ScrapedOpportunity
from ..models.opportunity import OpportunityType, OpportunityStatus


_AGENCIES = ["LTA", "MOE", "GovTech", "HDB", "MOH", "URA"]
_CATEGORIES = ["Goods", "Services", "Construction"]
_KEYWORDS = [
    "BIM Modelling Services",
    "Construction of Flyover",
    "Software Development for Schools",
    "Marketing & PR Campaign",
    "Land Transport Authority IT Upgrade",
    "Hospital Equipment Procurement",
]


class MockGeBIZScraper(BaseScraper):
    """
    Deterministic-ish mock scraper to develop/test the pipeline without
    hitting the real GeBIZ site. Emits ~20 opportunities per run; some
    share document_no across runs with evolving status so the diff logic
    can be exercised.
    """

    async def fetch(self) -> AsyncIterator[ScrapedOpportunity]:
        today = date.today()
        rnd = random.Random()
        for i in range(1, 21):
            doc_no = f"ITQ-2026{i:04d}"
            rnd.seed(doc_no)
            days_open = rnd.randint(2, 30)
            closing = datetime.combine(today + timedelta(days=days_open), datetime.min.time()).replace(hour=16)

            # Rotate status by run time so we get StatusChanged events on re-runs.
            status_pool = [
                OpportunityStatus.Open,
                OpportunityStatus.Open,
                OpportunityStatus.Open,
                OpportunityStatus.Closed,
                OpportunityStatus.PendingAward,
                OpportunityStatus.Awarded,
            ]
            status = status_pool[(i + datetime.utcnow().hour) % len(status_pool)]

            yield ScrapedOpportunity(
                document_no=doc_no,
                description=f"{rnd.choice(_KEYWORDS)} #{i}",
                agency=rnd.choice(_AGENCIES),
                opportunity_type=rnd.choice(list(OpportunityType)),
                published_date=today - timedelta(days=rnd.randint(0, 5)),
                closing_at=closing,
                status=status,
                procurement_category=rnd.choice(_CATEGORIES),
                contact_person=f"Officer {i} | officer{i}@gov.sg",
                source_url=f"https://www.gebiz.gov.sg/ptn/opportunity/{doc_no}",
                award_details={"supplier": "ACME Pte Ltd", "amount_sgd": 123456} if status == OpportunityStatus.Awarded else None,
            )
