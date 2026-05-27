from __future__ import annotations

import enum
from datetime import datetime, date
from sqlalchemy import String, Text, DateTime, Date, Enum, ForeignKey, JSON, Boolean, Integer, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class OpportunityType(str, enum.Enum):
    Auction = "Auction"
    Qualification = "Qualification"
    Quotation = "Quotation"
    RequestForInformation = "RequestForInformation"
    TenderLite = "TenderLite"
    Tender = "Tender"


class OpportunityStatus(str, enum.Enum):
    Open = "Open"
    Closed = "Closed"
    PendingAward = "PendingAward"
    Awarded = "Awarded"
    Cancelled = "Cancelled"
    NoAward = "NoAward"


class Opportunity(Base):
    __tablename__ = "opportunities"

    document_no: Mapped[str] = mapped_column(String(64), primary_key=True)
    reference_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    opportunity_type: Mapped[OpportunityType | None] = mapped_column(Enum(OpportunityType), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    agency: Mapped[str | None] = mapped_column(String(128), index=True)
    published_date: Mapped[date | None] = mapped_column(Date, index=True)
    closing_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    status: Mapped[OpportunityStatus] = mapped_column(Enum(OpportunityStatus), default=OpportunityStatus.Open, index=True)
    procurement_category: Mapped[str | None] = mapped_column(String(64))
    contact_person: Mapped[str | None] = mapped_column(Text)
    award_details: Mapped[dict | None] = mapped_column(JSON)
    source_url: Mapped[str | None] = mapped_column(String(512))

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    status_updates: Mapped[list["StatusUpdate"]] = relationship(
        back_populates="opportunity", cascade="all, delete-orphan", order_by="desc(StatusUpdate.changed_at)"
    )
    notes: Mapped[list["InternalNote"]] = relationship(
        back_populates="opportunity", cascade="all, delete-orphan", order_by="desc(InternalNote.created_at)"
    )
    watches: Mapped[list["Watch"]] = relationship(
        back_populates="opportunity", cascade="all, delete-orphan"
    )
    respondents: Mapped[list["OpportunityRespondent"]] = relationship(
        back_populates="opportunity", cascade="all, delete-orphan", order_by="desc(OpportunityRespondent.amount)"
    )


class OpportunityRespondent(Base):
    __tablename__ = "opportunity_respondents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_no: Mapped[str] = mapped_column(ForeignKey("opportunities.document_no", ondelete="CASCADE"), index=True)
    supplier_name: Mapped[str] = mapped_column(String(256), index=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_awarded: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    opportunity: Mapped[Opportunity] = relationship(back_populates="respondents")


class StatusUpdate(Base):
    __tablename__ = "status_updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_no: Mapped[str] = mapped_column(ForeignKey("opportunities.document_no", ondelete="CASCADE"), index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    from_status: Mapped[OpportunityStatus | None] = mapped_column(Enum(OpportunityStatus))
    to_status: Mapped[OpportunityStatus] = mapped_column(Enum(OpportunityStatus))
    note: Mapped[str | None] = mapped_column(Text)

    opportunity: Mapped[Opportunity] = relationship(back_populates="status_updates")


class InternalNote(Base):
    __tablename__ = "internal_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_no: Mapped[str] = mapped_column(ForeignKey("opportunities.document_no", ondelete="CASCADE"), index=True)
    author: Mapped[str] = mapped_column(String(64), default="anonymous")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    content: Mapped[str] = mapped_column(Text)

    opportunity: Mapped[Opportunity] = relationship(back_populates="notes")


class Watch(Base):
    __tablename__ = "watches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_no: Mapped[str] = mapped_column(ForeignKey("opportunities.document_no", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    opportunity: Mapped[Opportunity] = relationship(back_populates="watches")
