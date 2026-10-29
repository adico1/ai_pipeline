"""Compare requirements reviewers on fixed drafts, without running a writer."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ai_pipeline.cli import load_environment
from ai_pipeline.crewai_adapter import build_crew
from ai_pipeline.stage_contracts import RequirementsDocument
from evaluations.requirements_review.coverage import review_with_coverage


def review_document(document, task, model, output, requirements=None):
    """Use the production reviewer task with a saved writer output as context."""
    os.environ["CREWAI_STORAGE_DIR"] = str(output / "storage")
    crew = build_crew({
        "stage": "requirements",
        "task": task,
        "workspace": str(output),
        "output": str(output),
        "history": [],
        "crewai": {"model": model, "review_model": model, "max_iter": 24},
    })
    if requirements is not None:
        return review_with_coverage(crew, document, requirements)
    # Only the reviewer executes. Labels and mutation descriptions are not sent.
    result = crew.tasks[1].execute_sync(
        agent=crew.agents[1], context=json.dumps(document, ensure_ascii=False)
    )
    if result.pydantic is None:
        raise ValueError("Reviewer did not return a structured report")
    return result.pydantic.model_dump()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repetitions", type=int, default=2, choices=range(1, 4))
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--coverage", action="store_true", help="Evaluate exact draft citations and requirement coverage")
    args = parser.parse_args()
    fixture_path = Path(__file__).with_name("cases.json")
    task_path = ROOT / "projects/taskboard-rename-task.txt"
    cases = json.loads(fixture_path.read_text())
    requirements_path = Path(__file__).with_name("requirements.json")
    requirements = json.loads(requirements_path.read_text()) if args.coverage else None
    if requirements is not None:
        assert len({r["id"] for r in requirements}) == len(requirements)
        # This curated inventory must partition the entire original task in order.
        assert " ".join(r["task_quote"] for r in requirements).split() == task_path.read_text().split()
    for case in cases:
        RequirementsDocument.model_validate(case["document"])
    original = cases[0]["document"]
    for case in cases[1:]:
        expected = json.loads(json.dumps(original))
        expected["acceptance_criteria"].pop(case["removed_criterion_index"])
        assert case["document"] == expected, "Mutation changes more than its named criterion"
    if args.validate_only:
        print(f"Validated {len(cases)} drafts and their exact omissions; no API calls")
        return

    args.output.mkdir(parents=True, exist_ok=False)
    load_environment(ROOT / ".env")
    frozen_paths = [fixture_path, task_path, Path(__file__), ROOT / "ai_pipeline/prompts.py",
                    ROOT / "ai_pipeline/crewai_adapter.py"]
    if requirements is not None:
        frozen_paths.extend([requirements_path, Path(__file__).with_name("coverage.py")])
    frozen = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in frozen_paths}
    report = {
        "factory_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "input_hashes": frozen,
        "models": ["openai/gpt-4o-mini", "openai/gpt-4.1"],
        "repetitions": args.repetitions,
        "coverage_audit": args.coverage,
        "method": "Production CrewAI reviewer agent/task, temperature 0, saved document as task context; no writer, stage revision loop, or labels supplied to model.",
        "limitations": ["Small single-project sample; not a full lifecycle or broad reliability result.",
                        "Verdict agreement alone does not prove correct reasoning; inspect findings for the removed criterion.",
                        "Model/provider internal retries and structured-output conversion may occur; no evaluation-level retries."],
        "results": [],
    }
    for repetition in range(args.repetitions):
        # Reverse order in the second round to reduce simple order/time effects.
        models = report["models"] if repetition % 2 == 0 else list(reversed(report["models"]))
        for case in cases:
            for model in models:
                output = args.output / f"{repetition + 1}-{case['id']}-{model.split('/')[-1]}"
                output.mkdir()
                started = time.monotonic()
                row = {"case": case["id"], "model": model, "repetition": repetition + 1,
                       "expected_status": case["expected_status"]}
                try:
                    row["review"] = review_document(case["document"], task_path.read_text(), model, output, requirements)
                    row["verdict_matches"] = (row["review"]["status"] == case["expected_status"]
                                              and row["review"].get("evidence_valid", True))
                except Exception as exc:
                    row["error_type"] = type(exc).__name__
                    row["verdict_matches"] = False
                row["duration_seconds"] = round(time.monotonic() - started, 3)
                report["results"].append(row)
                (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
                print(json.dumps(row), flush=True)
    assert all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == digest
               for p, digest in frozen.items()), "Evaluation inputs changed"
    report["inputs_unchanged"] = True
    report["summary"] = {
        model: {"correct_verdicts": sum(r["verdict_matches"] for r in report["results"] if r["model"] == model),
                "total": sum(r["model"] == model for r in report["results"])}
        for model in report["models"]
    }
    (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
