from __future__ import annotations

from datetime import datetime, date
from typing import Optional, Any
from pydantic import BaseModel, ConfigDict, Field, computed_field

from .models.opportunity import OpportunityType, OpportunityStatus
from .models.notification import NotificationType


class OpportunityBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_no: str
    reference_no: Optional[str] = None
    opportunity_type: Optional[OpportunityType] = None
    description: str = ""
    agency: Optional[str] = None
    published_date: Optional[date] = None
    closing_at: Optional[datetime] = None
    status: OpportunityStatus = OpportunityStatus.Open
    procurement_category: Optional[str] = None
    contact_person: Optional[str] = None
    award_details: Optional[dict] = None
    source_url: Optional[str] = None

    @computed_field
    @property
    def source(self) -> str:
        if self.agency == "PSA" or (self.source_url and "singaporepsa.com" in self.source_url):
            return "PSA"
        return "GeBIZ"


class OpportunityListItem(OpportunityBase):
    is_watched: bool = False


class StatusUpdateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    changed_at: datetime
    from_status: Optional[OpportunityStatus]
    to_status: OpportunityStatus
    note: Optional[str] = None


class InternalNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    author: str
    created_at: datetime
    content: str


class InternalNoteIn(BaseModel):
    content: str = Field(min_length=1)
    author: Optional[str] = "default"


class OpportunityRespondentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_name: str
    amount: Optional[float] = None
    is_awarded: bool
    created_at: datetime


class OpportunityDetail(OpportunityBase):
    is_watched: bool = False
    status_updates: list[StatusUpdateOut] = []
    notes: list[InternalNoteOut] = []
    respondents: list[OpportunityRespondentOut] = []


class OpportunityListResponse(BaseModel):
    total: int
    page: int
    size: int
    items: list[OpportunityListItem]


class NotificationRuleIn(BaseModel):
    name: str = "默认规则"
    is_active: bool = True
    keywords: list[str] = []
    agencies: list[str] = []
    categories: list[str] = []
    countdown_days: list[int] = [3, 1]
    channel_in_app: bool = True
    channel_email: bool = False
    email_to: Optional[str] = None
    channel_webhook: bool = False
    webhook_url: Optional[str] = None


class NotificationRuleOut(NotificationRuleIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    updated_at: datetime


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: NotificationType
    title: str
    body: Optional[str]
    document_no: Optional[str]
    payload: Optional[dict] = None
    created_at: datetime
    read_at: Optional[datetime]


class ScrapeLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    finished_at: Optional[datetime]
    items_new: int
    items_updated: int
    status: str
    error: Optional[str]


class SupplierOut(BaseModel):
    supplier_name: str
    total_bids: int
    total_awards: int
    total_award_amount: float


class SupplierDetailOpportunity(BaseModel):
    document_no: str
    description: str
    status: OpportunityStatus
    published_date: Optional[date] = None
    amount: Optional[float] = None
    is_awarded: bool


class SupplierDetailOut(BaseModel):
    supplier_name: str
    total_bids: int
    total_awards: int
    total_award_amount: float
    bids: list[SupplierDetailOpportunity]
