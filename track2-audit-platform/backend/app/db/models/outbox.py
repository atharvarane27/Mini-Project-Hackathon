"""Durable transactional outbox."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, IdMixin


class OutboxEvent(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint(
            "event_type",
            "entity_id",
            "entity_version",
            name="event_entity_version",
        ),
        UniqueConstraint(
            "event_type",
            "entity_id",
            "payload_hash",
            name="event_entity_payload_hash",
        ),
        CheckConstraint("attempt_count >= 0", name="nonnegative_attempts"),
        Index("ix_outbox_available", "status", "available_at", "claimed_until"),
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_version: Mapped[int] = mapped_column(nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(nullable=False)
    claimed_at: Mapped[datetime | None]
    claimed_until: Mapped[datetime | None]
    claim_owner: Mapped[str | None] = mapped_column(String(128))
    last_error: Mapped[str | None] = mapped_column(String(1000))
