"""DFS color-cycle detection with a readable cycle path."""

from __future__ import annotations

from .dag import WorkflowDag


def find_cycle(graph: WorkflowDag) -> tuple[str, ...] | None:
    color = {task_id: 0 for task_id in graph.nodes}
    parent: dict[str, str] = {}

    def visit(task_id: str) -> tuple[str, ...] | None:
        color[task_id] = 1
        for child in sorted(graph.outgoing[task_id]):
            if color[child] == 0:
                parent[child] = task_id
                cycle = visit(child)
                if cycle is not None:
                    return cycle
            elif color[child] == 1:
                path = [task_id]
                while path[-1] != child:
                    path.append(parent[path[-1]])
                path.reverse()
                path.append(child)
                return tuple(path)
        color[task_id] = 2
        return None

    for task_id in sorted(graph.nodes):
        if color[task_id] == 0:
            cycle = visit(task_id)
            if cycle is not None:
                return cycle
    return None
