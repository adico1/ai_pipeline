"""Experimental coverage review; citations are checked before accepting a verdict."""

import json
from typing import Literal

from pydantic import BaseModel, Field


class DraftCitation(BaseModel):
    field: Literal["objective", "scope", "acceptance_criteria", "constraints", "open_questions"]
    index: int | None = Field(default=None, ge=0, strict=True)
    quote: str = Field(min_length=1)


class CoverageItem(BaseModel):
    requirement_id: str
    coverage: Literal["covered", "missing", "partial", "contradicted"]
    citations: list[DraftCitation]
    explanation: str = Field(min_length=1)


class CoverageReview(BaseModel):
    items: list[CoverageItem]


def validate_coverage(review, document, requirements):
    """Check identifiers and literal draft evidence, not semantic entailment."""
    expected = {item["id"] for item in requirements}
    ids = [item.requirement_id for item in review.items]
    errors = []
    if len(ids) != len(set(ids)) or set(ids) != expected:
        errors.append("Coverage must contain every required ID exactly once and no other IDs")
    for item in review.items:
        if item.coverage == "covered" and not item.citations:
            errors.append(f"{item.requirement_id}: covered claim lacks draft evidence")
        for citation in item.citations:
            value = document.get(citation.field)
            if isinstance(value, list):
                if citation.index is None or citation.index >= len(value):
                    errors.append(f"{item.requirement_id}: invalid draft list index")
                    continue
                value = value[citation.index]
            elif citation.index is not None:
                errors.append(f"{item.requirement_id}: scalar field cannot have an index")
                continue
            if not isinstance(value, str) or not citation.quote.strip() or citation.quote not in value:
                errors.append(f"{item.requirement_id}: quotation not found in referenced draft field")
    uncovered = [item.requirement_id for item in review.items if item.coverage != "covered"]
    return {
        "status": "blocked" if errors or uncovered else "passed",
        "evidence_valid": not errors,
        "validation_errors": errors,
        "uncovered_requirements": uncovered,
        "coverage": review.model_dump(),
    }


def review_with_coverage(crew, document, requirements):
    review = crew.tasks[1]
    review.output_pydantic = CoverageReview
    review.expected_output = "A coverage item for every supplied requirement ID, with exact draft citations."
    review.description += (
        "\nCOVERAGE AUDIT: The original task defines what is required; it is NOT proof "
        "that the delivered draft contains it. The supplied context is the DRAFT TO "
        "REVIEW. For each requirement below, compare ALL of its clauses against that "
        "draft. Return covered only when the draft explicitly covers every clause, "
        "using equivalent wording if appropriate. Use partial for incomplete coverage, "
        "missing for absent coverage, or contradicted for conflicting behavior. "
        "For evidence cite exact substrings of the draft, with the actual field name "
        "and zero-based list index (null for objective). Never cite the original task "
        "as draft evidence, invent quotations or infer absent details from the task. "
        "A missing requirement may have no citations. Explain the specific absent "
        "clauses for partial/missing rows. A broad statement such as preserve behavior "
        "does not replace explicit measurable criteria. Do not invent additional "
        "requirements. Return each ID exactly once.\nREQUIREMENTS TO CHECK:\n"
        + json.dumps(requirements, ensure_ascii=False)
    )
    result = review.execute_sync(
        agent=crew.agents[1], context="DRAFT TO REVIEW (only citation source):\n" + json.dumps(document, ensure_ascii=False)
    )
    if not isinstance(result.pydantic, CoverageReview):
        raise ValueError("Reviewer did not return structured coverage")
    return validate_coverage(result.pydantic, document, requirements)
