"""Versioned workflow templates and atomic dependency unlocking."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from uuid import uuid4

from .dag import TaskEdge, TaskNode, WorkflowDag
from .toposort import topological_sort


class TemplateStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class TaskState(StrEnum):
    LOCKED = "LOCKED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


class WorkflowNotFoundError(KeyError):
    pass


class WorkflowStateError(ValueError):
    pass


class WorkflowConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WorkflowTemplate:
    template_id: str
    name: str
    version: int
    status: TemplateStatus
    nodes: tuple[TaskNode, ...]
    edges: tuple[TaskEdge, ...]
    topological_order: tuple[str, ...]
    created_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "version": self.version,
            "status": self.status.value,
            "nodes": [
                {"task_id": node.task_id, "name": node.name} for node in self.nodes
            ],
            "edges": [
                {
                    "prerequisite_id": edge.prerequisite_id,
                    "dependent_id": edge.dependent_id,
                }
                for edge in self.edges
            ],
            "topological_order": list(self.topological_order),
        }


@dataclass(frozen=True, slots=True)
class WorkflowTask:
    task_id: str
    state: TaskState
    row_version: int = 1


@dataclass(frozen=True, slots=True)
class WorkflowInstance:
    instance_id: str
    case_id: str
    template_id: str
    tasks: tuple[WorkflowTask, ...]
    row_version: int

    def as_dict(self) -> dict[str, object]:
        return {
            "instance_id": self.instance_id,
            "case_id": self.case_id,
            "template_id": self.template_id,
            "row_version": self.row_version,
            "tasks": [
                {
                    "task_id": task.task_id,
                    "state": task.state.value,
                    "row_version": task.row_version,
                }
                for task in self.tasks
            ],
        }


class InMemoryWorkflowRepository:
    def __init__(self) -> None:
        self._lock = Lock()
        self._templates: dict[str, WorkflowTemplate] = {}
        self._template_ids_by_name: dict[str, list[str]] = {}
        self._instances: dict[str, WorkflowInstance] = {}
        self._instance_ids_by_case: dict[str, str] = {}

    def create_template(
        self,
        name: str,
        nodes: tuple[TaskNode, ...],
        edges: tuple[TaskEdge, ...],
        order: tuple[str, ...],
        now: datetime,
    ) -> WorkflowTemplate:
        with self._lock:
            version = len(self._template_ids_by_name.get(name, [])) + 1
            template = WorkflowTemplate(
                str(uuid4()), name, version, TemplateStatus.DRAFT,
                nodes, edges, order, now,
            )
            self._templates[template.template_id] = template
            self._template_ids_by_name.setdefault(name, []).append(template.template_id)
            return template

    def activate(self, template_id: str) -> WorkflowTemplate:
        with self._lock:
            try:
                current = self._templates[template_id]
            except KeyError as error:
                raise WorkflowNotFoundError(template_id) from error
            if current.status is not TemplateStatus.DRAFT:
                raise WorkflowStateError("only a DRAFT template can be activated")
            for other_id in self._template_ids_by_name[current.name]:
                other = self._templates[other_id]
                if other.status is TemplateStatus.ACTIVE:
                    self._templates[other_id] = replace(
                        other, status=TemplateStatus.RETIRED
                    )
            active = replace(current, status=TemplateStatus.ACTIVE)
            self._templates[template_id] = active
            return active

    def get_template(self, template_id: str) -> WorkflowTemplate:
        with self._lock:
            try:
                return self._templates[template_id]
            except KeyError as error:
                raise WorkflowNotFoundError(template_id) from error

    def start_instance(self, case_id: str, template_id: str) -> WorkflowInstance:
        with self._lock:
            existing = self._instance_ids_by_case.get(case_id)
            if existing is not None:
                return self._instances[existing]
            template = self._templates.get(template_id)
            if template is None:
                raise WorkflowNotFoundError(template_id)
            if template.status is not TemplateStatus.ACTIVE:
                raise WorkflowStateError("workflow template must be ACTIVE")
            incoming = {node.task_id: 0 for node in template.nodes}
            for edge in template.edges:
                incoming[edge.dependent_id] += 1
            tasks = tuple(
                WorkflowTask(
                    task_id,
                    TaskState.READY if incoming[task_id] == 0 else TaskState.LOCKED,
                )
                for task_id in template.topological_order
            )
            instance = WorkflowInstance(
                str(uuid4()), case_id, template_id, tasks, row_version=1
            )
            self._instances[instance.instance_id] = instance
            self._instance_ids_by_case[case_id] = instance.instance_id
            return instance

    def get_case_instance(self, case_id: str) -> WorkflowInstance:
        with self._lock:
            try:
                return self._instances[self._instance_ids_by_case[case_id]]
            except KeyError as error:
                raise WorkflowNotFoundError(case_id) from error

    def complete_task(
        self,
        case_id: str,
        task_id: str,
        expected_instance_version: int | None = None,
    ) -> WorkflowInstance:
        with self._lock:
            try:
                instance = self._instances[self._instance_ids_by_case[case_id]]
            except KeyError as error:
                raise WorkflowNotFoundError(case_id) from error
            if (
                expected_instance_version is not None
                and instance.row_version != expected_instance_version
            ):
                raise WorkflowConflictError("workflow instance version changed")
            template = self._templates[instance.template_id]
            states = {task.task_id: task for task in instance.tasks}
            try:
                current = states[task_id]
            except KeyError as error:
                raise WorkflowNotFoundError(task_id) from error
            if current.state not in {TaskState.READY, TaskState.IN_PROGRESS}:
                raise WorkflowStateError("only READY or IN_PROGRESS tasks can complete")
            states[task_id] = replace(
                current, state=TaskState.COMPLETE, row_version=current.row_version + 1
            )
            for edge in template.edges:
                dependent = states[edge.dependent_id]
                if dependent.state is not TaskState.LOCKED:
                    continue
                prerequisites = (
                    candidate.prerequisite_id
                    for candidate in template.edges
                    if candidate.dependent_id == edge.dependent_id
                )
                if all(states[item].state is TaskState.COMPLETE for item in prerequisites):
                    states[edge.dependent_id] = replace(
                        dependent,
                        state=TaskState.READY,
                        row_version=dependent.row_version + 1,
                    )
            updated = replace(
                instance,
                tasks=tuple(states[item] for item in template.topological_order),
                row_version=instance.row_version + 1,
            )
            self._instances[instance.instance_id] = updated
            return updated


class WorkflowService:
    def __init__(self, repository: InMemoryWorkflowRepository) -> None:
        self.repository = repository

    def validate(
        self, nodes: tuple[TaskNode, ...], edges: tuple[TaskEdge, ...]
    ) -> tuple[str, ...]:
        return topological_sort(WorkflowDag(nodes, edges))

    def create_template(
        self,
        name: str,
        nodes: tuple[TaskNode, ...],
        edges: tuple[TaskEdge, ...],
        *,
        activate: bool = False,
    ) -> WorkflowTemplate:
        normalized = name.strip()
        if not normalized:
            raise ValueError("template name must not be empty")
        order = self.validate(nodes, edges)
        template = self.repository.create_template(
            normalized, nodes, edges, order, datetime.now(UTC)
        )
        return self.repository.activate(template.template_id) if activate else template

    def activate(self, template_id: str) -> WorkflowTemplate:
        template = self.repository.get_template(template_id)
        self.validate(template.nodes, template.edges)
        return self.repository.activate(template_id)

    def start(self, case_id: str, template_id: str) -> WorkflowInstance:
        return self.repository.start_instance(case_id, template_id)

    def complete_task(
        self,
        case_id: str,
        task_id: str,
        expected_instance_version: int | None = None,
    ) -> WorkflowInstance:
        return self.repository.complete_task(
            case_id, task_id, expected_instance_version
        )

    def get_case_workflow(self, case_id: str) -> WorkflowInstance:
        return self.repository.get_case_instance(case_id)
