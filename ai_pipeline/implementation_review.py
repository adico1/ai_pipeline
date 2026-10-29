"""Bind implementation review verdicts to the reviewer's current evidence."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from ai_pipeline.engine import digest_tree
from ai_pipeline.stage_contracts import StageReport


class ReviewCitation(BaseModel):
    kind: Literal["source", "check"]
    quote: str = Field(min_length=1, max_length=4000)
    path: str | None = None
    check_stage: Literal["verify", "security"] | None = None


class BlockingFinding(BaseModel):
    finding: str = Field(min_length=1)
    citations: list[ReviewCitation] = Field(min_length=1)


class ImplementationReview(StageReport):
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    blocking_findings: list[BlockingFinding]


REVIEW_INSTRUCTIONS = (
    " Call check_current_candidate yourself before returning a verdict. Copy its "
    "source_digest into your report. The writer's old checks do not count as your "
    "review. For blocked, put every blocking claim in blocking_findings with a "
    "finding and citations. Each citation has kind source or check and an exact "
    "quote. A source citation needs a relative path and a unique exact passage "
    "from the CURRENT file. A check citation needs check_stage verify or security "
    "and an exact substring of that current failing check's returned evidence. "
    "Never cite a passing check as failed. Set findings to the same finding texts "
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
        with (self.output / "reviewer-checks.jsonl").open("a") as stream:
            stream.write(json.dumps(self.latest) + "\n")
        return payload

    def validate(self, report):
        errors, locations = [], []
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
            for citation in finding.citations:
                if citation.kind == "check":
                    check = checks.get(citation.check_stage)
                    if citation.path or not check or check.get("status") == "passed":
                        errors.append("Check citation must reference a current failed or unavailable check")
                    elif not citation.quote.strip() or citation.quote not in json.dumps(check, ensure_ascii=False):
                        errors.append("Check quotation not found in current reviewer evidence")
                else:
                    try:
                        if not citation.path or citation.check_stage:
                            raise ValueError("Source citation requires only a relative path")
                        path = self.resolve_source(Path(self.context["workspace"]), citation.path)
                        if path.stat().st_size > 128000:
                            raise ValueError("Source citation exceeds file size limit")
                        source = path.read_text()
                        if not citation.quote.strip() or source.count(citation.quote) != 1:
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
