# Current-evidence implementation review

Implementation reviewers now have a private evidence receipt populated only by
their own `check_current_candidate` tool. Writer checks do not satisfy it. The factory binds the
assembled review to the current check receipt and source digest. Passing requires both checks to pass
and no blocking findings; it does not bypass later verification or approvals.

Each blocked finding must cite either a current failed/unavailable check and an
stable evidence ID, or an allowed source file and a unique exact passage.
Source line locations are resolved by code. Stale evidence, uncited blockers,
claims that a passing check failed, invalid paths and invented source quotations are
rejected. The reviewer gets one correction attempt; persistent invalid reports
stop the stage. A valid source defect may block even with passing checks.

The validator checks evidence provenance and reference validity, not whether
the cited passage really proves the claimed defect. Independent review, human
approval, and external checks remain necessary. Results are recorded in
`reviewer-checks.jsonl` and `implementation-review-validation.jsonl`.

Run the bounded reviewer-only comparison using the generated candidate from the
previous failed trial and an isolated copy with one whitespace-trimming defect:

```sh
uv run python evaluations/implementation_review/run.py \
  --source-run 661421cdcbae --output .factory/implementation-review-controls
```

The evaluator uses the saved run's production reviewer model, copies only source,
tests and documentation, and first verifies that each fixture has the intended
independent check result. It then runs only the reviewer, withholding expected
labels. The original run is checked for changes. A failed evaluation-level call
is not retried; CrewAI may use the one report-correction attempt. Inspect the
findings as well as verdicts before considering a new trial.

Check evidence IDs are derived from the stage, status and structured failure
content, excluding output paths. The reviewer selects an ID; the factory attaches
the original evidence to `resolved_check_evidence`, replacing any model-supplied
contents. IDs are resolved only against this reviewer’s latest receipt. Findings
must describe observed mismatches. Optional `inferred_cause` requires a current
source citation. These rules cannot establish semantic correctness by themselves.

Accepted reports now separate check facts from model interpretations. The factory
renders expected/actual field differences (JSON Pointer paths) from cited evidence;
unchanged fields are not described as failures. For command-response envelopes,
structured expected values are compared with the returned `body`. Textual
expectations and other formats are displayed literally without a diagnosis.
The complete original evidence remains attached, including exit codes.

All original model prose, diagnoses and suggested repairs are retained under
`unverified_model_interpretation`. Canonical summaries and findings are generated
by code; source concerns remain explicitly unverified. This preserves the
reviewer's verdict and does not bypass checks or establish semantic correctness.

## Model response contract

The implementation reviewer returns only `status`, `evidence_ids`,
`source_concerns` and `commentary`. The check tool supplies
`allowed_evidence_ids`; selections must belong to that latest receipt. Unknown
IDs are rejected with the allowed choices, never guessed or translated from test
names. Extra report fields are rejected. Source concerns contain a relative path,
an exact unique current quote, and unverified commentary.

The factory assembles the full stage report, including source digest, check stage,
findings, summaries and attached evidence. The reviewer still owns the verdict;
passing requires both checks to pass and no blocking selections. One correction
is allowed. This removes redundant fields without relaxing current-evidence or
source-review requirements.
