"""Validate a complete task checklist, then audit a saved draft one item at a time."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ai_pipeline.cli import load_environment
from ai_pipeline.stage_contracts import RequirementsDocument
from evaluations.requirements_review.run import review_document

DIRECTORY = Path(__file__).resolve().parent
MODEL = "openai/gpt-4.1"


def load_checklist():
    checklist = json.loads((DIRECTORY / "taskboard-full-checklist.json").read_text())
    groups = json.loads((DIRECTORY / "requirements.json").read_text())
    task = (ROOT / "projects/taskboard-rename-task.txt").read_text()
    if " ".join(group["task_quote"] for group in groups).split() != task.split():
        raise ValueError("Source groups no longer cover the original task")
    source = {group["id"]: group["task_quote"] for group in groups}
    if {item["group"] for item in checklist} != set(source):
        raise ValueError("Checklist must represent every source group")
    if len({item["id"] for item in checklist}) != len(checklist):
        raise ValueError("Duplicate checklist IDs")
    for item in checklist:
        if item["task_quote"] != source[item["group"]] or not item["requirement"].strip():
            raise ValueError("Checklist item lacks a valid original-task reference")
    return checklist, task


def control_document(item, present):
    """A unit control for one rule; not a complete project requirements document."""
    return {
        "objective": "Specify the requested Taskboard change.",
        "scope": ["Taskboard project"],
        "acceptance_criteria": [item["requirement"] if present else "No implementation has been performed yet."],
        "constraints": ["This document describes intended future behavior."],
        "open_questions": [],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--controls", action="store_true")
    mode.add_argument("--document", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    checklist, task = load_checklist()
    document = json.loads(args.document.read_text()) if args.document else None
    if document is not None:
        RequirementsDocument.model_validate(document)
    for item in checklist:
        for present in (True, False):
            RequirementsDocument.model_validate(control_document(item, present))
    if args.validate_only:
        print(f"Validated {len(checklist)} checklist items, source groups and control schemas")
        return
    args.output.mkdir(parents=True, exist_ok=False)
    load_environment(ROOT / ".env")
    paths = [DIRECTORY / name for name in (
        "full_check.py", "taskboard-full-checklist.json", "requirements.json", "run.py", "coverage.py"
    )] + [ROOT / "ai_pipeline/prompts.py", ROOT / "ai_pipeline/crewai_adapter.py",
         ROOT / "projects/taskboard-rename-task.txt"]
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    report = {
        "factory_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "model": MODEL, "mode": "controls" if args.controls else "advisory",
        "input_hashes": hashes, "item_count": len(checklist), "results": [],
        "limitations": ["Checklist completeness was manually reviewed; matching source groups is not semantic proof.",
                        "Unit controls isolate each rule; they do not prove performance on complex drafts.",
                        "Advisory only: human approval and independent application checks remain required."],
    }
    if document is not None:
        report["document"] = document
        report["document_sha256"] = hashlib.sha256(args.document.read_bytes()).hexdigest()
    for item in checklist:
        variants = (True, False) if args.controls else (None,)
        for present in variants:
            draft = control_document(item, present) if args.controls else document
            label = "present" if present else "omitted" if args.controls else "draft"
            output = args.output / f"{item['id']}-{label}"
            output.mkdir()
            row = {"requirement_id": item["id"], "variant": label}
            if args.controls:
                row["expected_status"] = "passed" if present else "blocked"
            started = time.monotonic()
            try:
                # Only the rule and its origin reach the model; no control label.
                requirement = {key: item[key] for key in ("id", "requirement", "task_quote")}
                row["review"] = review_document(draft, task, MODEL, output, [requirement])
                row["valid_evidence"] = row["review"]["evidence_valid"]
                if args.controls:
                    row["correct"] = row["valid_evidence"] and row["review"]["status"] == row["expected_status"]
            except Exception as exc:
                row["error_type"] = type(exc).__name__
                row["valid_evidence"] = False
                if args.controls:
                    row["correct"] = False
            row["duration_seconds"] = round(time.monotonic() - started, 3)
            report["results"].append(row)
            (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(row), flush=True)
    if any(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest for name, digest in hashes.items()):
        raise ValueError("Frozen evaluation inputs changed")
    report["inputs_unchanged"] = True
    report["all_controls_passed"] = all(row["correct"] for row in report["results"]) if args.controls else None
    report["review_needed"] = [row["requirement_id"] for row in report["results"]
                               if not row["valid_evidence"] or row.get("review", {}).get("status") != "passed"]
    (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"completed": len(report["results"]), "all_controls_passed": report["all_controls_passed"]}))


if __name__ == "__main__":
    main()
