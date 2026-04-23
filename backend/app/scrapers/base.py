from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, AsyncIterator

from ..models.opportunity import OpportunityType, OpportunityStatus


@dataclass
class ScrapedOpportunity:
    document_no: str
    description: str = ""
    agency: Optional[str] = None
    opportunity_type: Optional[OpportunityType] = None
    published_date: Optional[date] = None
    closing_at: Optional[datetime] = None
    status: OpportunityStatus = OpportunityStatus.Open
    procurement_category: Optional[str] = None
    contact_person: Optional[str] = None
    award_details: Optional[dict] = None
    source_url: Optional[str] = None


class BaseScraper(ABC):
    """
    Scrapers yield ScrapedOpportunity items. The sync service diffs them
    against the DB to detect new records and status changes.
    """

    @abstractmethod
    async def fetch(self) -> AsyncIterator[ScrapedOpportunity]:
        ...
