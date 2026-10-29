"""Build paired drafts with one precise requirement removed per negative case."""

from copy import deepcopy


def atomic_cases(complete_document, checklist, original_task):
    cases = []
    ids = set()
    for check in checklist:
        if check["id"] in ids:
            raise ValueError("Duplicate atomic requirement ID")
        ids.add(check["id"])
        if not check["task_quote"] or check["task_quote"] not in original_task:
            raise ValueError("Checklist quotation must come from the original task")
        index = check["criterion_index"]
        criterion = complete_document["acceptance_criteria"][index]
        if not check["remove_text"] or criterion.count(check["remove_text"]) != 1:
            raise ValueError("Mutation must match exactly one passage")
        requirement = {key: check[key] for key in ("id", "requirement", "task_quote")}
        for present in (True, False):
            document = deepcopy(complete_document)
            if not present:
                document["acceptance_criteria"][index] = criterion.replace(
                    check["remove_text"], check["replacement"], 1
                )
            cases.append({
                "id": f"{check['id']}-{'present' if present else 'omitted'}",
                "expected_status": "passed" if present else "blocked",
                "document": document,
                "requirements": [requirement],
            })
    return cases
