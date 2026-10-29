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
