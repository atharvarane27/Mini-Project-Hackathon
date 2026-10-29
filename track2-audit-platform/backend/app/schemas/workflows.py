"""Pydantic v2 schemas for DAG workflow templates and runtime instances.

Workflow templates are versioned and immutable after activation.
Runtime cases get an instantiated DAG with tasks locked to the template
version at claim time. All models are frozen per P01 contract specification.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

# ---------------------------------------------------------------------------
# Template enums
# ---------------------------------------------------------------------------


class WorkflowTemplateStatus(StrEnum):
    """Lifecycle status of a workflow template version."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


# ---------------------------------------------------------------------------
# Task template
# ---------------------------------------------------------------------------


class WorkflowTaskTemplate(BaseModel):
    """A single node in a workflow template DAG.

    Maps to workflow_task_templates table:
    (id PK, template_id FK, stable_key, display_name, UNIQUE(template_id,stable_key)).
    stable_key is the immutable identifier used by workflow_edges.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    template_id: str
    stable_key: str
    display_name: str
    description: str | None = None
    assignable_roles: tuple[str, ...] = Field(default_factory=tuple)


class WorkflowEdge(BaseModel):
    """Directed prerequisite edge in a workflow template DAG.

    Maps to workflow_edges table:
    (template_id FK, predecessor_template_task_id FK,
     successor_template_task_id FK, composite PK).
    Both predecessor and successor must belong to the same template.
    """

    model_config = ConfigDict(frozen=True)

    template_id: str
    predecessor_task_stable_key: str
    successor_task_stable_key: str

    @model_validator(mode="after")
    def reject_self_edge(self) -> WorkflowEdge:
        if self.predecessor_task_stable_key == self.successor_task_stable_key:
            raise ValueError(
                f"Self-edge not allowed: task '{self.predecessor_task_stable_key}' "
                "cannot depend on itself"
            )
        return self


# ---------------------------------------------------------------------------
# Workflow template
# ---------------------------------------------------------------------------


class WorkflowTemplateCreate(BaseModel):
    """Request body for POST /workflows/templates (creates DRAFT version)."""

    model_config = ConfigDict(frozen=True)

    name: str
    task_templates: tuple[dict[str, Any], ...]
    edges: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    description: str | None = None


class WorkflowTemplate(BaseModel):
    """Persisted workflow template entity.

    Maps to workflow_templates table:
    (id PK, name, version, status, UNIQUE(name,version)).
    Immutable after activation per PRD section 3 M07.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    version: StrictInt = 1
    status: WorkflowTemplateStatus = WorkflowTemplateStatus.DRAFT
    description: str | None = None
    tasks: tuple[WorkflowTaskTemplate, ...] = Field(default_factory=tuple)
    edges: tuple[WorkflowEdge, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_version_positive(self) -> WorkflowTemplate:
        if self.version < 1:
            raise ValueError(f"Template version must be >= 1, got {self.version}")
        return self


# ---------------------------------------------------------------------------
# DAG validation
# ---------------------------------------------------------------------------


class DagValidationError(BaseModel):
    """Structured error for DAG topology violations."""

    model_config = ConfigDict(frozen=True)

    code: str  # e.g. CYCLIC_DEPENDENCY, MISSING_TASK, DUPLICATE_EDGE, SELF_EDGE
    message: str
    involved_keys: tuple[str, ...] = Field(default_factory=tuple)


class DagValidationResult(BaseModel):
    """Response from POST /workflows/validate.

    is_valid=False with errors if Kahn/DFS finds any topology violation.
    topological_order is populated only when is_valid=True.
    """

    model_config = ConfigDict(frozen=True)

    is_valid: bool
    errors: tuple[DagValidationError, ...] = Field(default_factory=tuple)
    topological_order: tuple[str, ...] = Field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Case workflow runtime
# ---------------------------------------------------------------------------


class CaseWorkflow(BaseModel):
    """Snapshot of the active workflow instance for a case.

    task_states maps stable_key → TaskState string so the UI can render
    the DAG with per-node coloring.
    unlockable_keys lists tasks whose all prerequisites are now COMPLETED
    and which may start immediately.
    """

    model_config = ConfigDict(frozen=True)

    case_id: str
    template_id: str
    template_version: StrictInt
    task_states: dict[str, str] = Field(default_factory=dict)
    unlockable_keys: tuple[str, ...] = Field(default_factory=tuple)
    edges: tuple[WorkflowEdge, ...] = Field(default_factory=tuple)


class TaskCompleteRequest(BaseModel):
    """Request body to mark a workflow task as completed."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    expected_row_version: StrictInt
    notes: str | None = None
