"""Bind implementation review verdicts to the reviewer's current evidence."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_pipeline.engine import digest_tree
from ai_pipeline.evidence_facts import describe_check
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
    unverified_model_interpretation: dict = Field(default_factory=dict)


class SourceConcern(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    quote: str = Field(min_length=1, max_length=4000)
    commentary: str = Field(min_length=1)


class ReviewSelection(BaseModel):
    """Small model-facing response; the factory owns the full stage report."""
    model_config = ConfigDict(extra="forbid")
    status: Literal["passed", "blocked"]
    evidence_ids: list[str]
    source_concerns: list[SourceConcern]
    commentary: str


REVIEW_INSTRUCTIONS = (
    " Call check_current_candidate yourself before returning a verdict. "
    "Return ONLY status, evidence_ids, source_concerns and commentary. "
    "Select evidence_ids verbatim from the returned allowed_evidence_ids list. "
    "Do not invent IDs or derive them from test names. Code resolves each ID "
    "against your latest check receipt and generates factual findings. "
    "For source defects not covered by checks, use source_concerns with path, "
    "a unique exact quote from the current file, and commentary. "
    "For passed, both lists must be empty and both checks must pass. "
    "For blocked, select at least one check ID or source concern. "
    "Commentary is explicitly unverified; do not infer causes from test names. "
    "Do not return summary, findings, source_digest, or other report fields. "
    "The factory assembles those fields. Return one JSON object."
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
        self.latest["allowed_evidence_ids"] = list(entries)
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

    def attach_facts(self, report):
        """Keep model prose visible without presenting it as measured evidence."""
        for finding in report.blocking_findings:
            facts = []
            for citation in finding.citations:
                if citation.kind == 'check':
                    facts.append(describe_check(report.resolved_check_evidence[citation.evidence_id]))
                else:
                    facts.append(f'Unverified source concern at {citation.path}; quoted passage exists, but the claimed defect requires review.')
            finding.finding = "\n".join(dict.fromkeys(facts))
            finding.inferred_cause = None
        report.findings = [item.finding for item in report.blocking_findings]
        report.summary = (
            'Reviewer passed; current verify and security checks passed. Model interpretation is unverified.'
            if report.status == 'passed' else
            'Reviewer blocked; see recorded check facts and explicitly unverified source concerns.'
        )
        report.next_actions = []

    def assemble(self, selection):
        """Resolve only current selections; never guess or repair unknown IDs."""
        if self.latest is None:
            raise ValueError("Reviewer must call check_current_candidate itself")
        entries = self.latest["check_evidence"]
        unknown = sorted(set(selection.evidence_ids) - entries.keys())
        if unknown:
            raise ValueError(f"Unknown evidence IDs: {unknown}. Allowed IDs: {list(entries)}")
        blockers = []
        for key in dict.fromkeys(selection.evidence_ids):
            blockers.append(BlockingFinding(
                finding=describe_check(entries[key]),
                citations=[ReviewCitation(kind="check", check_stage=entries[key]["stage"], evidence_id=key)],
            ))
        for concern in selection.source_concerns:
            blockers.append(BlockingFinding(
                finding=concern.commentary,
                citations=[ReviewCitation(kind="source", path=concern.path, quote=concern.quote)],
            ))
        return ImplementationReview(
            status=selection.status, summary=selection.commentary or "Reviewer selection",
            findings=[item.finding for item in blockers], next_actions=[],
            blocking_findings=blockers, source_digest=self.latest["source_digest"],
        )

    def guardrail(self, output):
        report, locations = None, []
        try:
            selection = (output.pydantic if isinstance(output.pydantic, ReviewSelection)
                         else ReviewSelection.model_validate_json(output.raw))
            report = self.assemble(selection)
            errors, locations = self.validate(report)
        except (ValueError, ValidationError) as exc:
            errors = [str(exc)]
        with (self.output / "implementation-review-validation.jsonl").open("a") as stream:
            stream.write(json.dumps({"valid": not errors, "errors": errors,
                                     "raw_report": output.raw, "source_locations": locations}) + "\n")
        if errors:
            return False, "REVIEW EVIDENCE INVALID: " + json.dumps(errors)
        self.attach_facts(report)
        report.unverified_model_interpretation = {
            "commentary": selection.commentary,
            "source_concerns": [item.model_dump() for item in selection.source_concerns],
        }
        output.pydantic = report
        output.raw = report.model_dump_json()
        output.json_dict = None
        return True, output
