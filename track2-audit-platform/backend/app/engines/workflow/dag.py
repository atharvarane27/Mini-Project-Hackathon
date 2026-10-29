"""Custom adjacency-list workflow graph."""

from __future__ import annotations

from dataclasses import dataclass


class WorkflowGraphError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TaskNode:
    task_id: str
    name: str

    def __post_init__(self) -> None:
        if not self.task_id.strip() or not self.name.strip():
            raise WorkflowGraphError("task ID and name must not be empty")


@dataclass(frozen=True, slots=True, order=True)
class TaskEdge:
    prerequisite_id: str
    dependent_id: str


class WorkflowDag:
    def __init__(self, nodes: tuple[TaskNode, ...], edges: tuple[TaskEdge, ...]) -> None:
        self.nodes: dict[str, TaskNode] = {}
        for node in nodes:
            if node.task_id in self.nodes:
                raise WorkflowGraphError(f"duplicate task {node.task_id!r}")
            self.nodes[node.task_id] = node
        if not self.nodes:
            raise WorkflowGraphError("workflow must contain at least one task")
        self.outgoing = {task_id: set[str]() for task_id in self.nodes}
        self.incoming = {task_id: set[str]() for task_id in self.nodes}
        for edge in edges:
            if edge.prerequisite_id not in self.nodes or edge.dependent_id not in self.nodes:
                raise WorkflowGraphError("edge references an unknown task")
            if edge.prerequisite_id == edge.dependent_id:
                raise WorkflowGraphError("self-dependency is not allowed")
            if edge.dependent_id in self.outgoing[edge.prerequisite_id]:
                raise WorkflowGraphError("duplicate edge is not allowed")
            self.outgoing[edge.prerequisite_id].add(edge.dependent_id)
            self.incoming[edge.dependent_id].add(edge.prerequisite_id)
        self.edges = tuple(sorted(edges))
