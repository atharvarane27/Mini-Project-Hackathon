"""Deterministic Kahn topological ordering."""

from __future__ import annotations

import heapq

from .cycle_detection import find_cycle
from .dag import WorkflowDag


class WorkflowCycleError(ValueError):
    def __init__(self, cycle: tuple[str, ...]) -> None:
        self.cycle = cycle
        super().__init__(f"workflow cycle detected: {' -> '.join(cycle)}")


def topological_sort(graph: WorkflowDag) -> tuple[str, ...]:
    indegree = {task_id: len(graph.incoming[task_id]) for task_id in graph.nodes}
    ready = [task_id for task_id, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        task_id = heapq.heappop(ready)
        ordered.append(task_id)
        for child in sorted(graph.outgoing[task_id]):
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, child)
    if len(ordered) != len(graph.nodes):
        cycle = find_cycle(graph)
        raise WorkflowCycleError(cycle or ())
    return tuple(ordered)
