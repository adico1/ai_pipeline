"""Read-only operator guidance derived from recorded run state."""

import shlex
from pathlib import Path

from .engine import STAGES


def brief(value, limit=350):
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[:limit] + "…"


def format_status(state, state_dir, env_file):
    run_id = state["id"]
    status = state["status"]
    index = state["stage"]
    stage = STAGES[index] if index < len(STAGES) else "complete"
    attempts = state.get("attempts", [])
    directory = Path(state_dir).resolve() / run_id
    prefix = [
        "uv",
        "run",
        "ai-pipeline",
        "--state-dir",
        str(Path(state_dir).resolve()),
        "--env-file",
        str(Path(env_file).resolve()),
    ]

    def command(name, *args):
        return shlex.join(prefix + [name, run_id, *args])

    lines = [
        f"Run: {run_id} | Project: {state['project']}",
        f"Status: {status}" + (" (simulated demo)" if state.get("demo") else ""),
        f"Stage: {stage} ({min(index + 1, len(STAGES))}/{len(STAGES)})",
        f"Attempts: {len(attempts)} | Failed attempts: {sum(a['status'] == 'failed' for a in attempts)} | Engine repairs: {state.get('repairs', 0)}",
    ]
    if attempts:
        latest = attempts[-1]
        result = latest.get("result") or {}
        lines.append(f"Latest attempt: {latest['stage']} — {latest['status']}")
        for label, value in (
            ("Summary", result.get("summary")),
            ("Error", latest.get("error")),
            ("Stop reason", result.get("stop_reason")),
        ):
            if value:
                lines.append(f"{label}: {brief(value)}")
        failures = result.get("failed_cases") or []
        if failures:
            lines.append(
                f"Failed checks in latest result: {len(failures)} (up to 5 shown)"
            )
            lines.extend(f"  - {brief(case)}" for case in failures[:5])
        if latest["status"] == "failed" and result.get("findings"):
            lines.append("Findings in latest failed attempt (up to 5 shown):")
            lines.extend(f"  - {brief(item)}" for item in result["findings"][:5])
    lines += [
        "",
        f"Evidence: {directory / 'artifacts'}",
        f"Candidate source: {directory / 'workspace'}",
    ]
    latest_by_stage = {a["stage"]: a for a in attempts}
    for name, attempt in latest_by_stage.items():
        if attempt.get("artifact_directory"):
            lines.append(
                f"  {name} ({attempt['status']}): {Path(attempt['artifact_directory']).resolve()}"
            )

    lines.append("")
    if status == "completed":
        lines.append(
            "Next: no further action required for this run. Review observe evidence for the delivered result."
        )
    elif status == "awaiting_approval":
        guidance = {
            "design": "Review requirements: objective, scope, acceptance criteria and open questions.",
            "release": "Review candidate source, verify/security results and code review. Confirm general behavior, not just passing examples.",
            "deploy": "Review release package and digest manifest. Confirm they match verified source and the intended deployment target.",
        }
        lines.append(f"Approval required before {stage}.")
        lines.append(
            guidance.get(
                stage,
                "Review the preceding stage artifacts and candidate source before approving.",
            )
        )
        lines.append(
            "A waiting gate is not proof that approval is appropriate. Resolve any known review findings first."
        )
        lines.append(
            "After review, replace YOUR_NAME and the review note with your actual assessment:"
        )
        lines.append(
            command(
                "approve",
                "--actor",
                "YOUR_NAME",
                "--note",
                "Describe the evidence reviewed and approval rationale",
            )
        )
        lines.append("Then advance (approval alone does not execute the stage):")
        lines.append(command("advance"))
    elif status == "failed":
        delivery_started = any(a["stage"] in {"release", "deploy"} for a in attempts)
        if stage in {"release", "deploy"} or delivery_started:
            lines.append(
                "Next: reconcile delivery and source/evidence state before creating a new run. Do not replay delivery or blindly retry this run."
            )
        else:
            lines.append(
                "Next: inspect the latest evidence and fix the cause before retrying. Do not repeat unchanged failures."
            )
            lines.append(
                "If configuration or task must change, create a new run instead. Otherwise, after resolving the cause:"
            )
            lines.append(command("retry"))
            lines.append(command("advance"))
    elif status in {"queued", "ready"}:
        lines += ["Next: advance to the next gate or result:", command("advance")]
    elif status == "running":
        lines.append(
            "Next: wait for the active process. This saved state alone cannot distinguish active execution from an interruption; confirm the process stopped before recovery."
        )
    else:
        lines.append("Next: inspect the full state before taking action.")
    lines += ["", "Full recorded state:", command("status", "--json")]
    return "\n".join(lines)
