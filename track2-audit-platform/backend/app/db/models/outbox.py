from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, utc_now


class OutboxEvent(Base):
    """3NF Transactional Outbox Event entity.

    Guarantees reliable at-least-once cross-process dispatch between PostgreSQL and the
    in-memory priority heap worker without distributed 2PC.

    Unique constraint: UNIQUE(event_type, entity_id, payload_hash) prevents duplicate event staging.
    Index: (status, created_at) for efficient worker polling and queue claims.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint(
            "event_type",
            "entity_id",
            "payload_hash",
            name="uq_outbox_events_dedup",
        ),
        Index("ix_outbox_events_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
