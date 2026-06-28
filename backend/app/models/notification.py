from __future__ import annotations

import enum
from datetime import datetime
from sqlalchemy import String, DateTime, Enum, Integer, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class NotificationType(str, enum.Enum):
    NewMatch = "NewMatch"          # 关键词匹配的新商机
    ClosingSoon = "ClosingSoon"    # 截标倒计时
    StatusChanged = "StatusChanged"  # 关注项目状态变更
    System = "System"              # 系统消息（抓取失败等）


class NotificationRule(Base):
    __tablename__ = "notification_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    name: Mapped[str] = mapped_column(String(64), default="默认规则")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    keywords: Mapped[list] = mapped_column(JSON, default=list)            # ["LTA", "Construction", ...]
    agencies: Mapped[list] = mapped_column(JSON, default=list)            # ["LTA", "GovTech", ...]
    categories: Mapped[list] = mapped_column(JSON, default=list)          # ["Services", "Goods", ...]
    countdown_days: Mapped[list] = mapped_column(JSON, default=list)      # [3, 1]
    channel_in_app: Mapped[bool] = mapped_column(Boolean, default=True)
    channel_email: Mapped[bool] = mapped_column(Boolean, default=False)
    email_to: Mapped[str | None] = mapped_column(String(256))
    channel_webhook: Mapped[bool] = mapped_column(Boolean, default=False)
    webhook_url: Mapped[str | None] = mapped_column(String(512))
    webhook_keyword: Mapped[str | None] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    type: Mapped[NotificationType] = mapped_column(Enum(NotificationType))
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str | None] = mapped_column(String(2048))
    document_no: Mapped[str | None] = mapped_column(String(64), index=True)
    payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
