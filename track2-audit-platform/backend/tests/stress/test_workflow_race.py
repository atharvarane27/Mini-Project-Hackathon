"""P17 concurrent prerequisite completion test."""

from concurrent.futures import ThreadPoolExecutor

from app.engines.workflow.dag import TaskEdge, TaskNode
from app.engines.workflow.service import (
    InMemoryWorkflowRepository,
    TaskState,
    WorkflowService,
)


def test_concurrent_prerequisite_completion_unlocks_once_without_race() -> None:
    service = WorkflowService(InMemoryWorkflowRepository())
    nodes = tuple(TaskNode(f"prereq-{index}", f"Prerequisite {index}") for index in range(50)) + (
        TaskNode("final", "Final approval"),
    )
    edges = tuple(TaskEdge(f"prereq-{index}", "final") for index in range(50))
    template = service.create_template("race", nodes, edges, activate=True)
    service.start("case-race", template.template_id)

    with ThreadPoolExecutor(max_workers=50) as executor:
        list(
            executor.map(
                lambda task_id: service.complete_task("case-race", task_id),
                (f"prereq-{index}" for index in range(50)),
            )
        )

    instance = service.get_case_workflow("case-race")
    final = next(task for task in instance.tasks if task.task_id == "final")
    assert final.state is TaskState.READY
    assert final.row_version == 2
    assert sum(task.state is TaskState.COMPLETE for task in instance.tasks) == 50
