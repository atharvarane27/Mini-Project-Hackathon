"""Workflow validation, template creation, and case workflow routes."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from app.engines.workflow.dag import TaskEdge, TaskNode, WorkflowGraphError
from app.engines.workflow.service import WorkflowNotFoundError, WorkflowService
from app.engines.workflow.toposort import WorkflowCycleError
from app.schemas.workflows import WorkflowTemplateRequest, WorkflowValidateRequest


def _graph(request: WorkflowValidateRequest) -> tuple[tuple[TaskNode, ...], tuple[TaskEdge, ...]]:
    return (
        tuple(TaskNode(node.task_id, node.name) for node in request.nodes),
        tuple(
            TaskEdge(edge.prerequisite_id, edge.dependent_id)
            for edge in request.edges
        ),
    )


def create_workflows_router(service: WorkflowService) -> APIRouter:
    router = APIRouter()

    @router.post("/workflows/validate", response_model=None)
    def validate_workflow(
        request: WorkflowValidateRequest,
        request_id: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object] | JSONResponse:
        identifier = request_id or str(uuid4())
        try:
            order = service.validate(*_graph(request))
        except (WorkflowGraphError, WorkflowCycleError) as error:
            return JSONResponse(
                status_code=422,
                content={"error": {"code": "INVALID_WORKFLOW", "message": str(error)}, "request_id": identifier},
            )
        return {"data": {"valid": True, "topological_order": list(order)}, "meta": {}, "request_id": identifier}

    @router.post("/workflows/templates", status_code=201, response_model=None)
    def create_template(
        request: WorkflowTemplateRequest,
        request_id: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object] | JSONResponse:
        identifier = request_id or str(uuid4())
        try:
            template = service.create_template(
                request.name, *_graph(request), activate=request.activate
            )
        except (WorkflowGraphError, WorkflowCycleError) as error:
            return JSONResponse(
                status_code=422,
                content={"error": {"code": "INVALID_WORKFLOW", "message": str(error)}, "request_id": identifier},
            )
        return {"data": template.as_dict(), "meta": {}, "request_id": identifier}

    @router.get("/cases/{case_id}/workflow", response_model=None)
    def get_case_workflow(
        case_id: str,
        request_id: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object] | JSONResponse:
        identifier = request_id or str(uuid4())
        try:
            instance = service.get_case_workflow(case_id)
        except WorkflowNotFoundError:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "WORKFLOW_NOT_FOUND", "message": "workflow not found"}, "request_id": identifier},
            )
        return {"data": instance.as_dict(), "meta": {}, "request_id": identifier}

    return router
