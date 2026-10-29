"""Bind implementation review verdicts to the reviewer's current evidence."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from ai_pipeline.engine import digest_tree
from ai_pipeline.stage_contracts import StageReport


class ReviewCitation(BaseModel):
    kind: Literal["source", "check"]
    quote: str | None = Field(default=None, min_length=1, max_length=4000)
    evidence_id: str | None = None
    path: str | None = None
    check_stage: Literal["verify", "security"] | None = None


class BlockingFinding(BaseModel):
    finding: str = Field(min_length=1)
    inferred_cause: str | None = None
    citations: list[ReviewCitation] = Field(min_length=1)


class ImplementationReview(StageReport):
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    blocking_findings: list[BlockingFinding]
    resolved_check_evidence: dict[str, dict] = Field(default_factory=dict)


REVIEW_INSTRUCTIONS = (
    " Call check_current_candidate yourself before returning a verdict. Copy its "
    "source_digest into your report. The writer's old checks do not count as your "
    "review. For blocked, put every blocking claim in blocking_findings with a "
    "finding and citations. Write finding as an observed mismatch, not a guessed "
    "root cause. Put any inferred cause separately in inferred_cause and support "
    "it with a source citation. A source citation needs kind source, relative path "
    "and quote containing a unique exact CURRENT passage. A check citation needs "
    "kind check, check_stage, and an evidence_id copied from check_evidence. Leave "
    "quote and path null for check citations; code attaches the original evidence. "
    "Never infer broken SQL, isolation or completion flags merely from a title "
    "mismatch in a test with that name. Compare the actual fields with expected "
    "fields. Never cite a passing check as failed. Set findings to the same texts "
    "as blocking_findings, in order. For passed, blocking_findings must be empty "
    "and both current checks must pass. Passing checks do not rule out source "
    "defects: cite the current defective expression and explain the violated "
    "requirement. Do not invent absent behavior from historical baseline failures. "
    "Return one JSON object matching the requested structured report."
)


class ReviewerEvidence:
    def __init__(self, context, run_checks, resolve_source):
        self.context = context
        self.run_checks = run_checks
        self.resolve_source = resolve_source
        self.latest = None
        self.output = Path(context["output"])

    def check(self):
        """Only this reviewer's tool can establish its evidence receipt."""
        payload = self.run_checks(self.context)
        self.latest = json.loads(payload)
        entries = {}
        for check in self.latest.get("checks", []):
            if check.get("status") == "passed":
                continue
            report = check.get("report", {})
            examples = [group["example"] for group in report.get("failure_groups", [])
                        if "example" in group]
            for detail in examples or [report]:
                evidence = {"stage": check["stage"], "status": check["status"], "detail": detail}
                canonical = json.dumps(evidence, sort_keys=True, ensure_ascii=False)
                evidence_id = check["stage"] + ":" + hashlib.sha256(canonical.encode()).hexdigest()[:16]
                entries[evidence_id] = evidence
        self.latest["check_evidence"] = entries
        with (self.output / "reviewer-checks.jsonl").open("a") as stream:
            stream.write(json.dumps(self.latest) + "\n")
        return json.dumps(self.latest)

    def validate(self, report):
        errors, locations = [], []
        report.resolved_check_evidence = {}
        current = digest_tree(Path(self.context["workspace"]))
        if self.latest is None:
            return ["Reviewer must call check_current_candidate itself"], locations
        if self.latest.get("source_digest") != current or report.source_digest != current:
            errors.append("Review and reviewer check evidence must match CURRENT source_digest")
        checks = {row["stage"]: row for row in self.latest.get("checks", [])}
        if set(checks) != {"verify", "security"}:
            errors.append("Reviewer must obtain both configured checks")
        if report.status == "passed":
            if report.blocking_findings:
                errors.append("Passed review cannot contain blocking findings")
            if any(row.get("status") != "passed" for row in checks.values()):
                errors.append("Passed review requires passing current verify and security checks")
        else:
            if not report.blocking_findings:
                errors.append("Blocked review needs evidence-backed blocking findings")
            if report.findings != [item.finding for item in report.blocking_findings]:
                errors.append("Every findings entry must match a cited blocking finding")
        for finding in report.blocking_findings:
            if finding.inferred_cause and not any(c.kind == "source" for c in finding.citations):
                errors.append("An inferred cause requires a current source citation")
            for citation in finding.citations:
                if citation.kind == "check":
                    check = checks.get(citation.check_stage)
                    evidence = self.latest.get("check_evidence", {}).get(citation.evidence_id)
                    if citation.path or citation.quote or not check or check.get("status") == "passed":
                        errors.append("Check citation requires an evidence ID for a current unsuccessful check, without path or quote")
                    elif not evidence or evidence["stage"] != citation.check_stage:
                        errors.append("Unknown evidence ID or mismatched check stage")
                    else:
                        report.resolved_check_evidence[citation.evidence_id] = evidence
                else:
                    try:
                        if not citation.path or citation.check_stage or citation.evidence_id:
                            raise ValueError("Source citation requires only a relative path")
                        path = self.resolve_source(Path(self.context["workspace"]), citation.path)
                        if path.stat().st_size > 128000:
                            raise ValueError("Source citation exceeds file size limit")
                        source = path.read_text()
                        if not citation.quote or not citation.quote.strip() or source.count(citation.quote) != 1:
                            raise ValueError("Source quotation must match exactly one current passage")
                        locations.append({"path": citation.path,
                                          "line": source[:source.index(citation.quote)].count("\n") + 1,
                                          "quote": citation.quote})
                    except (OSError, ValueError, UnicodeError) as exc:
                        errors.append(str(exc))
        return errors, locations

    def guardrail(self, output):
        report, locations = None, []
        try:
            report = (output.pydantic if isinstance(output.pydantic, ImplementationReview)
                      else ImplementationReview.model_validate_json(output.raw))
            errors, locations = self.validate(report)
        except (ValueError, ValidationError) as exc:
            errors = [str(exc)]
        with (self.output / "implementation-review-validation.jsonl").open("a") as stream:
            stream.write(json.dumps({"valid": not errors, "errors": errors,
                                     "raw_report": output.raw, "source_locations": locations}) + "\n")
        if errors:
            return False, "REVIEW EVIDENCE INVALID: " + json.dumps(errors)
        output.pydantic = report
        output.raw = report.model_dump_json()
        output.json_dict = None
        return True, output
