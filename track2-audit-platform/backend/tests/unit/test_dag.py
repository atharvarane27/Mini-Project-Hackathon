"""P17 workflow DAG and lifecycle tests."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.workflows import create_workflows_router
from app.engines.workflow.cycle_detection import find_cycle
from app.engines.workflow.dag import (
    TaskEdge,
    TaskNode,
    WorkflowDag,
    WorkflowGraphError,
)
from app.engines.workflow.service import (
    InMemoryWorkflowRepository,
    TaskState,
    TemplateStatus,
    WorkflowService,
)
from app.engines.workflow.toposort import WorkflowCycleError, topological_sort


NODES = (
    TaskNode("branch_ledger", "Branch ledger clearance"),
    TaskNode("whistleblower", "Whistleblower audit"),
    TaskNode("escalation", "Escalation review"),
)
EDGES = (
    TaskEdge("branch_ledger", "escalation"),
    TaskEdge("whistleblower", "escalation"),
)


def state(instance, task_id: str) -> TaskState:
    return next(task.state for task in instance.tasks if task.task_id == task_id)


def test_topological_order_is_valid_and_deterministic() -> None:
    order = topological_sort(WorkflowDag(NODES, EDGES))
    assert order == ("branch_ledger", "whistleblower", "escalation")
    positions = {task_id: index for index, task_id in enumerate(order)}
    assert all(
        positions[edge.prerequisite_id] < positions[edge.dependent_id]
        for edge in EDGES
    )


def test_dfs_reports_readable_cycle_path() -> None:
    graph = WorkflowDag(
        NODES,
        (
            TaskEdge("branch_ledger", "whistleblower"),
            TaskEdge("whistleblower", "escalation"),
            TaskEdge("escalation", "branch_ledger"),
        ),
    )
    assert find_cycle(graph) == (
        "branch_ledger",
        "whistleblower",
        "escalation",
        "branch_ledger",
    )
    with pytest.raises(WorkflowCycleError, match="branch_ledger -> whistleblower"):
        topological_sort(graph)


@pytest.mark.parametrize(
    "nodes,edges,message",
    [
        ((TaskNode("a", "A"), TaskNode("a", "Again")), (), "duplicate task"),
        ((TaskNode("a", "A"),), (TaskEdge("a", "missing"),), "unknown"),
        ((TaskNode("a", "A"),), (TaskEdge("a", "a"),), "self-dependency"),
    ],
)
def test_invalid_graph_structure_is_rejected(nodes, edges, message: str) -> None:
    with pytest.raises(WorkflowGraphError, match=message):
        WorkflowDag(nodes, edges)


def test_both_prerequisites_are_required_before_escalation_unlocks() -> None:
    service = WorkflowService(InMemoryWorkflowRepository())
    template = service.create_template("track-2", NODES, EDGES, activate=True)
    instance = service.start("case-1", template.template_id)
    assert state(instance, "escalation") is TaskState.LOCKED

    after_ledger = service.complete_task("case-1", "branch_ledger")
    assert state(after_ledger, "escalation") is TaskState.LOCKED
    after_both = service.complete_task("case-1", "whistleblower")
    assert state(after_both, "escalation") is TaskState.READY


def test_new_activation_retires_prior_version() -> None:
    repository = InMemoryWorkflowRepository()
    service = WorkflowService(repository)
    first = service.create_template("review", NODES, EDGES, activate=True)
    second = service.create_template("review", NODES, EDGES, activate=True)
    assert repository.get_template(first.template_id).status is TemplateStatus.RETIRED
    assert second.status is TemplateStatus.ACTIVE
    assert second.version == 2


def test_invalid_cycle_does_not_alter_active_template() -> None:
    repository = InMemoryWorkflowRepository()
    service = WorkflowService(repository)
    active = service.create_template("safe", NODES, EDGES, activate=True)
    cyclic = EDGES + (TaskEdge("escalation", "branch_ledger"),)
    with pytest.raises(WorkflowCycleError):
        service.create_template("safe", NODES, cyclic, activate=True)
    assert repository.get_template(active.template_id).status is TemplateStatus.ACTIVE


def test_workflow_api_validates_creates_and_reads_case_instance() -> None:
    service = WorkflowService(InMemoryWorkflowRepository())
    app = FastAPI()
    app.include_router(create_workflows_router(service), prefix="/api/v1")
    client = TestClient(app)
    payload = {
        "nodes": [{"task_id": node.task_id, "name": node.name} for node in NODES],
        "edges": [
            {
                "prerequisite_id": edge.prerequisite_id,
                "dependent_id": edge.dependent_id,
            }
            for edge in EDGES
        ],
    }
    validated = client.post("/api/v1/workflows/validate", json=payload)
    assert validated.status_code == 200
    created = client.post(
        "/api/v1/workflows/templates",
        json={**payload, "name": "api-workflow", "activate": True},
    )
    template_id = created.json()["data"]["template_id"]
    service.start("case-api", template_id)
    fetched = client.get("/api/v1/cases/case-api/workflow")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["case_id"] == "case-api"

    invalid = client.post(
        "/api/v1/workflows/validate",
        json={
            "nodes": payload["nodes"],
            "edges": payload["edges"]
            + [{"prerequisite_id": "escalation", "dependent_id": "branch_ledger"}],
        },
    )
    assert invalid.status_code == 422
    assert "cycle" in invalid.json()["error"]["message"]
