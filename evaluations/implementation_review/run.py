"""Review a passing saved candidate and one deliberate defect without a writer."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ai_pipeline.cli import load_environment
from ai_pipeline.crewai_adapter import build_crew, run_candidate_checks
from ai_pipeline.engine import Factory, digest_tree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run = Factory(ROOT / ".factory").directory(args.source_run)
    state = json.loads((run / "state.json").read_text())
    config = json.loads((run / "config.json").read_text())
    source = run / "workspace"
    original_digest = digest_tree(source)
    args.output.mkdir(parents=True, exist_ok=False)
    load_environment(ROOT / ".env")
    frozen = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
        "ai_pipeline/implementation_review.py", "ai_pipeline/crewai_adapter.py",
        "ai_pipeline/prompts.py", "evaluations/implementation_review/run.py",
    )}
    report = {
        "factory_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_run": state["id"], "source_digest": original_digest, "input_hashes": frozen,
        "models": config["stages"]["implement"]["crewai"], "results": [],
        "limitations": ["One positive and one negative fixture, not broad model reliability evidence.",
                        "Citation checks prove reference validity, not semantic correctness.",
                        "Reviewer-only evaluation; no writer or full lifecycle stages execute."],
    }
    for variant in ("passing", "missing_whitespace_trim"):
        output = args.output / variant
        workspace = output / "workspace"
        workspace.mkdir(parents=True)
        # Copy only this project's explicit source/test/documentation roots.
        for name in ("taskboard", "tests"):
            shutil.copytree(source / name, workspace / name, ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("README.md", "pyproject.toml", ".gitignore"):
            shutil.copy2(source / name, workspace / name)
        if variant == "missing_whitespace_trim":
            path = workspace / "taskboard/domain.py"
            text = path.read_text()
            marker = "def rename_task("
            before, rename = text.split(marker, 1)
            if rename.count("trimmed = title.strip()") != 1:
                raise ValueError("Fixture no longer has the expected rename expression")
            path.write_text(before + marker + rename.replace("trimmed = title.strip()", "trimmed = title", 1))
        context = {"stage": "implement", "task": (run / "task.txt").read_text(),
                   "workspace": str(workspace.resolve()), "output": str(output.resolve()),
                   "history": [attempt for attempt in state["attempts"] if attempt["status"] == "passed"],
                   "crewai": config["stages"]["implement"]["crewai"],
                   "checks": {name: config["stages"][name] for name in ("verify", "security")}}
        preflight = json.loads(run_candidate_checks(context))
        checks_pass = all(check["status"] == "passed" for check in preflight["checks"])
        if checks_pass != (variant == "passing"):
            raise ValueError("Control candidate did not produce its expected independent check result")
        before_review = digest_tree(workspace)
        row = {"variant": variant, "expected_status": "passed" if checks_pass else "blocked",
               "preflight": preflight}
        os.environ["CREWAI_STORAGE_DIR"] = str(output / "storage")
        try:
            crew = build_crew(context)
            result = crew.tasks[1].execute_sync(agent=crew.agents[1], context="Inspect the candidate source and obtain your own current checks.")
            row["review"] = result.pydantic.model_dump()
            row["verdict_matches"] = row["review"]["status"] == row["expected_status"]
        except Exception as exc:
            row["error_type"] = type(exc).__name__
            row["error"] = str(exc)
            row["verdict_matches"] = False
        for filename, key in (("reviewer-checks.jsonl", "reviewer_checks"),
                              ("implementation-review-validation.jsonl", "report_validation")):
            path = output / filename
            row[key] = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        row["source_unchanged"] = before_review == digest_tree(workspace)
        report["results"].append(row)
        (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"variant": variant, "verdict_matches": row["verdict_matches"],
                          "reviewer_check_calls": len(row["reviewer_checks"])}), flush=True)
    assert digest_tree(source) == original_digest, "Original failed run changed"
    assert all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == value for name, value in frozen.items())
    report["inputs_unchanged"] = True
    report["all_controls_passed"] = all(row["verdict_matches"] and row["source_unchanged"] for row in report["results"])
    (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
