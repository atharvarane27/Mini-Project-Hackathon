"""Workflow graph API contracts."""

from pydantic import BaseModel, ConfigDict, Field


class WorkflowNodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)


class WorkflowEdgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prerequisite_id: str = Field(min_length=1, max_length=120)
    dependent_id: str = Field(min_length=1, max_length=120)


class WorkflowValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: list[WorkflowNodeRequest]
    edges: list[WorkflowEdgeRequest]


class WorkflowTemplateRequest(WorkflowValidateRequest):
    name: str = Field(min_length=1, max_length=120)
    activate: bool = False
