from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, utc_now


class WorkflowTemplate(Base):
    """3NF Workflow Template definition for audit review DAGs.

    Unique constraint: UNIQUE(name, version).
    """

    __tablename__ = "workflow_templates"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_workflow_templates_name_version"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships
    tasks: Mapped[list["WorkflowTaskTemplate"]] = relationship(
        "WorkflowTaskTemplate",
        back_populates="template",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    edges: Mapped[list["WorkflowEdge"]] = relationship(
        "WorkflowEdge",
        back_populates="template",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class WorkflowTaskTemplate(Base):
    """3NF Node definition in a Workflow Template DAG.

    Unique constraint: UNIQUE(template_id, stable_key).
    """

    __tablename__ = "workflow_task_templates"
    __table_args__ = (
        UniqueConstraint(
            "template_id", "stable_key", name="uq_workflow_task_templates_template_key"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    template_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workflow_templates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    stable_key: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    template: Mapped["WorkflowTemplate"] = relationship("WorkflowTemplate", back_populates="tasks")


class WorkflowEdge(Base):
    """3NF Prerequisite edge in a Workflow Template DAG.

    Composite PK: (template_id, predecessor_template_task_id, successor_template_task_id).
    CHECK constraint: predecessor != successor (no self-loops).
    """

    __tablename__ = "workflow_edges"
    __table_args__ = (
        CheckConstraint(
            "predecessor_template_task_id != successor_template_task_id",
            name="chk_workflow_edges_no_self_edge",
        ),
    )

    template_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workflow_templates.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    predecessor_template_task_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workflow_task_templates.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    successor_template_task_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workflow_task_templates.id", ondelete="RESTRICT"),
        primary_key=True,
    )

    # Relationships
    template: Mapped["WorkflowTemplate"] = relationship("WorkflowTemplate", back_populates="edges")
    predecessor_task: Mapped["WorkflowTaskTemplate"] = relationship(
        "WorkflowTaskTemplate",
        foreign_keys=[predecessor_template_task_id],
    )
    successor_task: Mapped["WorkflowTaskTemplate"] = relationship(
        "WorkflowTaskTemplate",
        foreign_keys=[successor_template_task_id],
    )
