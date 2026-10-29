from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, utc_now


class User(Base):
    """3NF User entity."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships
    role_links: Mapped[list["UserRole"]] = relationship(
        "UserRole",
        back_populates="user",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class Role(Base):
    """3NF Role entity."""

    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    user_links: Mapped[list["UserRole"]] = relationship(
        "UserRole",
        back_populates="role",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class UserRole(Base):
    """3NF Junction table mapping User to Role.

    Composite PK: (user_id, role_id).
    Strictly RESTRICT on delete.
    """

    __tablename__ = "user_roles"

    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    role_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("roles.id", ondelete="RESTRICT"),
        primary_key=True,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="role_links")
    role: Mapped["Role"] = relationship("Role", back_populates="user_links")
