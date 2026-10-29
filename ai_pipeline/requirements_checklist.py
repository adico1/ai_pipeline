"""Preserve operator-supplied acceptance rules in generated requirements."""

import json


def validate_checklist(checklist, task=None):
    if not isinstance(checklist, list) or not checklist or len(checklist) > 100:
        raise ValueError("Requirements checklist must contain 1 to 100 items")
    ids = set()
    for item in checklist:
        if not isinstance(item, dict) or set(item) != {"id", "requirement", "task_quote"}:
            raise ValueError("Checklist items require exactly id, requirement and task_quote")
        if any(not isinstance(value, str) or not value.strip() for value in item.values()):
            raise ValueError("Checklist fields must be nonempty strings")
        if item["id"] in ids:
            raise ValueError("Checklist IDs must be unique")
        ids.add(item["id"])
        if task is not None and item["task_quote"] not in task:
            raise ValueError(f"Checklist {item['id']}: task_quote is absent from the original task")


def document_errors(document, checklist):
    """Require every canonical rule verbatim at its declared criterion index."""
    errors = []
    entries = document.get("checklist", [])
    criteria = document.get("acceptance_criteria", [])
    expected = {item["id"]: item["requirement"] for item in checklist}
    ids = [entry.get("id") for entry in entries]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        errors.append("Map every checklist ID exactly once; no missing, duplicate or unknown IDs")
    indices = []
    for entry in entries:
        key = entry.get("id")
        index = entry.get("acceptance_criterion_index")
        if type(index) is not int or not 0 <= index < len(criteria):
            errors.append(f"{key}: invalid acceptance criterion index")
            continue
        indices.append(index)
        if key in expected and criteria[index] != expected[key]:
            errors.append(f"{key}: preserve the canonical requirement exactly: {expected[key]}")
    if len(indices) != len(set(indices)):
        errors.append("Each checklist item must map to a separate acceptance criterion")
    return errors


def assemble_requirements(analysis, checklist):
    """Combine strict writer-owned fields with the unchanged operator contract."""
    from ai_pipeline.stage_contracts import ChecklistRequirementsDocument, RequirementsAnalysis

    validate_checklist(checklist)
    validated = RequirementsAnalysis.model_validate(analysis)
    document = ChecklistRequirementsDocument(
        **validated.model_dump(),
        acceptance_criteria=[item["requirement"] for item in checklist],
        checklist=[{"id": item["id"], "acceptance_criterion_index": index}
                   for index, item in enumerate(checklist)],
    )
    errors = document_errors(document.model_dump(), checklist)
    if errors:
        raise ValueError("Assembled requirements failed validation: " + json.dumps(errors))
    return document


def assembly_guardrail(checklist, output_directory):
    """Give the reviewer the assembled document, retaining the writer's output."""
    from pydantic import ValidationError
    from ai_pipeline.stage_contracts import RequirementsAnalysis

    attempts = []

    def validate(output):
        authored = output.pydantic.model_dump() if output.pydantic is not None else None
        errors = []
        try:
            # CrewAI 1.9.3 invokes the first guardrail before schema conversion.
            if output.pydantic is None:
                analysis = RequirementsAnalysis.model_validate_json(output.raw)
            elif isinstance(output.pydantic, RequirementsAnalysis):
                analysis = output.pydantic
            else:
                raise ValueError("Writer must return a validated RequirementsAnalysis")
            authored = analysis.model_dump()
            document = assemble_requirements(authored, checklist)
        except (ValidationError, ValueError) as exc:
            errors = [str(exc)]
        attempts.append({"passed": not errors, "errors": errors,
                         "writer_analysis": authored, "writer_raw": output.raw})
        (output_directory / "requirements-checklist-validation.json").write_text(
            json.dumps({"mode": "deterministic_assembly", "attempts": attempts}, indent=2) + "\n"
        )
        if errors:
            return False, "REQUIREMENTS ANALYSIS INVALID: " + json.dumps(errors)
        (output_directory / "requirements-analysis.json").write_text(json.dumps(authored, indent=2) + "\n")
        # CrewAI passes TaskOutput.raw to the next task, so update both views.
        output.pydantic = document
        output.raw = document.model_dump_json(indent=2)
        output.json_dict = None
        return True, output

    return validate
