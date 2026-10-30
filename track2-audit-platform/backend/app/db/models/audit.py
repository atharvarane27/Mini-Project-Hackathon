"""Append-only activity ledger model."""

from sqlalchemy import ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, IdMixin


class ActivityLog(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "activity_log"
    __table_args__ = (Index("ix_activity_object_version", "object_id", "object_version"),)
    actor_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    object_type: Mapped[str] = mapped_column(String(80), nullable=False)
    object_id: Mapped[str] = mapped_column(String(128), nullable=False)
    object_version: Mapped[int] = mapped_column(nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    old_values: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    new_values: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
