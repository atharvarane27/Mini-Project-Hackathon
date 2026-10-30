"""Versioned workflow templates, dependencies, and case tasks."""

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, IdMixin


class WorkflowTemplate(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "workflow_templates"
    __table_args__ = (UniqueConstraint("name", "version"),)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)


class WorkflowTaskTemplate(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "workflow_task_templates"
    __table_args__ = (UniqueConstraint("template_id", "task_key"),)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_templates.id", ondelete="RESTRICT"), index=True
    )
    task_key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class WorkflowDependency(Base):
    __tablename__ = "workflow_dependencies"
    prerequisite_task_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_task_templates.id", ondelete="RESTRICT"), primary_key=True
    )
    dependent_task_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_task_templates.id", ondelete="RESTRICT"), primary_key=True
    )


class CaseWorkflowTask(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "case_workflow_tasks"
    __table_args__ = (
        UniqueConstraint("case_id", "task_template_id"),
        CheckConstraint("row_version > 0", name="positive_row_version"),
    )
    case_id: Mapped[str] = mapped_column(
        ForeignKey("audit_cases.id", ondelete="RESTRICT"), index=True
    )
    task_template_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_task_templates.id", ondelete="RESTRICT")
    )
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    row_version: Mapped[int] = mapped_column(default=1, nullable=False)
    assignee_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
