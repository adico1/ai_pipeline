# Current-evidence implementation review

Implementation reviewers now have a private evidence receipt populated only by
their own `check_current_candidate` tool. Writer checks do not satisfy it. A
review must name the current source digest. Passing requires both checks to pass
and no blocking findings; it does not bypass later verification or approvals.

Each blocked finding must cite either a current failed/unavailable check and an
exact evidence quote, or an allowed source file and a unique exact passage.
Source line locations are resolved by code. Stale evidence, uncited blockers,
claims that a passing check failed, invalid paths and invented quotations are
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
