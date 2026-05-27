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
                reference_no=f"REF-2026-MOCK-{i:03d}",
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

    async def enrich_opportunity(self, doc_no: str) -> Optional[ScrapedOpportunity]:
        import re
        match = re.search(r"(\d+)$", doc_no)
        i = int(match.group(1)) if match else 1
        
        rnd = random.Random()
        rnd.seed(doc_no)
        today = date.today()
        days_open = rnd.randint(2, 30)
        closing = datetime.combine(today + timedelta(days=days_open), datetime.min.time()).replace(hour=16)

        status_pool = [
            OpportunityStatus.Open,
            OpportunityStatus.Open,
            OpportunityStatus.Open,
            OpportunityStatus.Closed,
            OpportunityStatus.PendingAward,
            OpportunityStatus.Awarded,
        ]
        status = status_pool[(i + datetime.utcnow().hour) % len(status_pool)]

        respondents = []
        award_details = None

        suppliers = [
            "ACME Supplies Pte Ltd",
            "BuildCorp Engineering Singapore",
            "Global Solutions Asia-Pacific",
            "Sintech Systems",
        ]
        opp_suppliers = [suppliers[(i + offset) % len(suppliers)] for offset in range(3)]

        if status == OpportunityStatus.Closed:
            for name in opp_suppliers:
                respondents.append({
                    "supplier_name": name,
                    "amount": None,
                    "is_awarded": False
                })
        elif status == OpportunityStatus.PendingAward:
            for idx, name in enumerate(opp_suppliers):
                respondents.append({
                    "supplier_name": name,
                    "amount": float(100000 + (idx * 25000) + (i * 1000)),
                    "is_awarded": False
                })
        elif status == OpportunityStatus.Awarded:
            awarded_supplier = opp_suppliers[0]
            award_amount = float(120000 + (i * 1000))
            for idx, name in enumerate(opp_suppliers):
                is_awd = name == awarded_supplier
                respondents.append({
                    "supplier_name": name,
                    "amount": award_amount if is_awd else float(130000 + (idx * 15000)),
                    "is_awarded": is_awd
                })
            award_details = {
                "supplier_name": awarded_supplier,
                "amount": award_amount,
                "awarded_date": today.isoformat()
            }

        return ScrapedOpportunity(
            document_no=doc_no,
            reference_no=f"REF-2026-MOCK-{i:03d}",
            description=f"{rnd.choice(_KEYWORDS)} #{i}",
            agency=rnd.choice(_AGENCIES),
            opportunity_type=rnd.choice(list(OpportunityType)),
            published_date=today - timedelta(days=rnd.randint(0, 5)),
            closing_at=closing,
            status=status,
            procurement_category=rnd.choice(_CATEGORIES),
            contact_person=f"Officer {i} | officer{i}@gov.sg",
            source_url=f"https://www.gebiz.gov.sg/ptn/opportunity/{doc_no}",
            award_details=award_details,
            respondents=respondents,
        )
