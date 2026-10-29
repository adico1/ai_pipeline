"""Validated stage deliverables shared by CrewAI tasks and their reviewers."""

from typing import Literal
from pydantic import BaseModel, Field


class StageReport(BaseModel):
    status: Literal["passed", "blocked"]
    summary: str = Field(min_length=1)
    findings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class RequirementsDocument(BaseModel):
    objective: str = Field(min_length=1)
    scope: list[str] = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    constraints: list[str] = Field(min_length=1)
    open_questions: list[str] = Field(default_factory=list)


class ChecklistMapping(BaseModel):
    id: str = Field(min_length=1)
    acceptance_criterion_index: int = Field(ge=0, strict=True)


class ChecklistRequirementsDocument(RequirementsDocument):
    checklist: list[ChecklistMapping]


class DesignDocument(BaseModel):
    approach: str = Field(min_length=1)
    interfaces: list[str] = Field(min_length=1)
    data_flow: list[str] = Field(min_length=1)
    decisions_and_tradeoffs: list[str] = Field(min_length=1)
    edge_cases: list[str] = Field(min_length=1)
    verification_strategy: list[str] = Field(min_length=1)
    open_questions: list[str] = Field(default_factory=list)


class PlanStep(BaseModel):
    action: str = Field(min_length=1)
    target: str = Field(min_length=1)
    done_when: str = Field(min_length=1)


class PlanDocument(BaseModel):
    objective: str = Field(min_length=1)
    ordered_steps: list[PlanStep] = Field(min_length=1)
    verification_steps: list[str] = Field(min_length=1)
    risks_and_mitigations: list[str] = Field(min_length=1)


DOCUMENTS = {
    "requirements": RequirementsDocument,
    "design": DesignDocument,
    "plan": PlanDocument,
}


class StageState(BaseModel):
    context: dict = Field(default_factory=dict)
    report: dict = Field(default_factory=dict)
