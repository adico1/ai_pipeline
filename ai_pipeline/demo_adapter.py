"""Deterministic example adapter. No LLM, network, release, or deployment."""

import importlib.util
import json
import os
from pathlib import Path


def main():
    context = json.loads(Path(os.environ["FACTORY_CONTEXT"]).read_text())
    output = Path(os.environ["FACTORY_OUTPUT"])
    workspace = Path(context["workspace"])
    stage = context["stage"]
    status = "passed"
    details = {}
    summaries = {
        "requirements": "Accept addition over positive, negative, and zero integers.",
        "design": "Keep a pure add(a, b) function with no external dependencies.",
        "plan": "Correct arithmetic and verify against an external scenario suite.",
        "security": "Demo-only static check: calculator source contains only the expected pure function.",
        "review": "Demo-only review: scenario evidence is available for operator inspection.",
        "release": "SIMULATED release: local manifest only; nothing published.",
        "deploy": "SIMULATED deployment: local receipt only; no service started.",
        "observe": "SIMULATED observation: no production telemetry was collected.",
        "retrospective": "Demo lifecycle complete. A real project needs agent, delivery, and telemetry adapters.",
    }
    if stage == "implement":
        prior = context.get("previous_attempt")
        # First attempt deliberately does not fix the bug, exercising repair feedback.
        if prior and prior["stage"] == "verify" and prior["status"] == "failed":
            (workspace / "calculator.py").write_text(
                "def add(a, b):\n    return a + b\n"
            )
            summary = (
                "Repaired arithmetic after receiving independent scenario failures."
            )
        else:
            summary = (
                "Initial candidate submitted; independent verification must assess it."
            )
    elif stage == "verify":
        spec = importlib.util.spec_from_file_location(
            "candidate", workspace / "calculator.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cases = [(2, 3, 5), (-4, -7, -11), (0, 8, 8), (7, -7, 0)]
        details["scenarios"] = [
            {
                "inputs": [a, b],
                "expected": expected,
                "actual": module.add(a, b),
                "passed": module.add(a, b) == expected,
            }
            for a, b, expected in cases
        ]
        status = (
            "passed" if all(c["passed"] for c in details["scenarios"]) else "failed"
        )
        summary = f"Independent addition scenarios {status}."
    else:
        summary = summaries[stage]
        if (
            stage == "security"
            and (workspace / "calculator.py").read_text()
            != "def add(a, b):\n    return a + b\n"
        ):
            status = "failed"
        if stage in {"release", "deploy"}:
            details["simulated"] = True
    (output / "result.json").write_text(
        json.dumps({"status": status, "summary": summary, **details}, indent=2)
    )
    print(summary)
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
