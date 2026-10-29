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


def writer_guardrail(checklist, output_directory):
    """Reject lossy drafts before the independent reviewer sees them."""
    attempts = []

    def validate(output):
        document = output.pydantic.model_dump() if output.pydantic is not None else {}
        errors = document_errors(document, checklist)
        attempts.append({"passed": not errors, "errors": errors})
        (output_directory / "requirements-checklist-validation.json").write_text(
            json.dumps({"attempts": attempts}, indent=2) + "\n"
        )
        if errors:
            return False, "REQUIREMENTS CHECKLIST INCOMPLETE: " + json.dumps(errors)
        return True, output

    return validate
