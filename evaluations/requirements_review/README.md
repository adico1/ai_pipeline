# Requirements reviewer comparison

This bounded evaluation compares `openai/gpt-4o-mini` and `openai/gpt-4.1`
using the factory's production requirements reviewer agent and task. It executes
only the reviewer, passing a saved document as task context. It does not run a
writer, stage revisions, or a full lifecycle trial.

`cases.json` contains a complete draft checked against
`projects/taskboard-rename-task.txt` and three copies with exactly one acceptance
criterion removed: the error contract, preservation of existing task data, or
regression tests. These are operator-authored evaluation fixtures, not generated
application artifacts. Expected statuses and explanations are withheld from the
model. Both models receive identical documents and instructions.

Validate the fixture schemas and exact omissions without API calls:

```sh
uv run python evaluations/requirements_review/run.py \
  --output /tmp/requirements-review-unused --validate-only
```

Run two repetitions per model and case (16 reviews, using configured API keys):

```sh
uv run python evaluations/requirements_review/run.py \
  --output .factory/requirements-review-comparison
```

The output directory must be new. Results are saved after each review in
`results.json`; inputs are hashed and checked for changes. No evaluation-level
retries occur. Provider retries and structured-output conversion may occur.
Repetition two reverses the model order. Credentials are loaded from the
factory's existing `.env` and are not included in reports.

Inspect findings, not only verdict counts: a blocked draft is useful evidence
only when the reviewer identifies its actual omission. Select neither model
unless it accepts the complete draft in both repetitions and identifies each
deliberate omission in both repetitions. A passing comparison supports a fresh
trial with frozen settings; it does not establish general review reliability.

## Coverage audit experiment

Add `--coverage` to evaluate the same drafts with an explicit coverage table.
`requirements.json` partitions the original task into nine named groups, checked
against the complete task text before execution. Each reviewer must classify
every group and quote the delivered draft using a field and zero-based index.
The evaluator verifies literal quotes, references, unique IDs and evidence for
covered claims. Any uncovered group blocks the draft. Invalid evidence is an
evaluation failure, not a successful detection of a deliberately omitted rule.

```sh
uv run python evaluations/requirements_review/run.py --coverage \
  --output .factory/requirements-coverage-comparison
```

This experiment extends the production reviewer task's instructions and output
schema only inside the evaluator. It does not enable a new production gate or
change model selection. The original fixtures, models and two repetitions remain
unchanged. Literal citation validation cannot establish semantic completeness;
inspect the coverage explanations and retained quotations before drawing a
conclusion. The task inventory is curated for this project, not an automatic
requirements extractor.

## Single-requirement experiment

`--atomic` uses a focused three-item acceptance checklist in
`atomic-checklist.json`: invalid-input exit code 2, preservation of the insertion
sequence, and temporary databases for tests. Each item quotes the original task
and states one rule. This checklist is a diagnostic subset, not a replacement
for the full task or its nine-group inventory.

For each item the evaluator sends the complete draft, then a copy with only the
named phrase removed or replaced. Other criteria remain unchanged. The reviewer
sees one checklist item per call; expected verdicts and mutation instructions
are withheld. Two repetitions for two models produce 24 reviews. The existing
literal citation validator still applies. All six verdicts per repetition must
be correct, with valid citations and explanations identifying the omitted detail,
before considering a model suitable for another experiment.

```sh
uv run python evaluations/requirements_review/run.py --atomic --validate-only \
  --output /tmp/atomic-unused
uv run python evaluations/requirements_review/run.py --atomic \
  --output .factory/requirements-atomic-comparison
```

Human requirements approval and independent application checks remain necessary.
Neither this evaluator nor its results automatically approve a factory run,
change model settings, or enable a new production gate.

## Full Taskboard checklist and supervised trial

`taskboard-full-checklist.json` expands the entire original task into 55 review
items tied to its nine source groups. Each item is reviewed individually by
GPT-4.1. Some cohesive interface rules retain multiple related details; the
reviewer must cover the complete selected rule. The inventory was manually
checked against the task; source-group validation alone cannot prove completeness.

First run positive/negative unit controls for every item (110 reviews). Each
positive document contains only that selected rule; the negative replaces it
with a neutral statement. These simple controls validate rule recognition and
citation handling; the earlier six paired full-document drafts provide additional
evidence for three rules. Neither proves reliability on every real draft.

```sh
uv run python evaluations/requirements_review/full_check.py --controls \
  --output .factory/taskboard-full-controls
```

After inspecting the controls, create a fresh supervised run:

```sh
uv run ai-pipeline create --config projects/taskboard-rename-supervised.json \
  --task "$(cat projects/taskboard-rename-task.txt)"
uv run ai-pipeline advance RUN_ID
```

At the design approval gate, audit the saved requirements document:

```sh
uv run python evaluations/requirements_review/full_check.py \
  --document /absolute/path/to/requirements.json \
  --output .factory/taskboard-requirements-advisory
```

Inspect every coverage result alongside the task and draft. An advisory never
approves a run. Resolve or withhold approval for real omissions; record evidence
for any false-positive finding in the human approval note. Preserve the original
task as the acceptance contract. Release/deploy still require source review,
independent application checks and normal approvals.

The separate supervised configuration changes only the project name and broad
requirements reviewer to GPT-4.1; its writer and downstream stages are unchanged.
The broad verdict alone is insufficient (as the prior negative controls showed).
The full checklist review plus human approval is the intended safeguard. No
existing configuration or historical run is rewritten.
