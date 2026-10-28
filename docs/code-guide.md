# Reading the pipeline code

Start with `Factory.advance()` in `ai_pipeline/engine.py`. It is the outer lifecycle:
load the run, check whether evidence is still valid, pause for approval if required,
execute one stage, then choose the next stage or a bounded repair. It stops at an
approval gate, failure, or completion.

## Module map

| File | Responsibility |
| --- | --- |
| `ai_pipeline/cli.py` | Parse commands, load environment settings, call the factory. |
| `ai_pipeline/engine.py` | Persist runs, isolate workspaces, enforce gates, run adapters, record evidence. |
| `ai_pipeline/crewai_adapter.py` | Build specialist/reviewer crews, provide source/check tools, enforce completion and progress. |
| `ai_pipeline/prompts.py` | Stage roles and specialist/reviewer instructions. Read this to understand what agents are asked to do. |
| `ai_pipeline/stage_contracts.py` | Structured requirements, design, plan and review schemas. |
| `ai_pipeline/status.py` | Render recorded state and operator guidance without advancing a run. |
| `ai_pipeline/command_adapter.py` | Wrap a configured command in the result-file protocol. |
| `integrations/` | Project-specific acceptance checks, limited policy checks, packaging and local delivery. |

## One stage, end to end

1. `Factory.advance()` saves `running` before starting work. If the process is
   interrupted, another call cannot silently replay the stage.
2. `Factory.execute()` creates an attempt directory and writes `context.json`.
   That context includes task, history, workspace, output paths and trusted checks.
3. `_run_adapter()` starts either the CrewAI adapter or the configured command,
   captures stdout/stderr, and enforces a timeout.
4. The adapter writes `result.json`. `_read_adapter_result()` validates its status
   and summary without hiding an earlier execution error.
5. `execute()` compares source digests, writes `evidence.json`, and appends the
   attempt to the run. `advance()` decides whether to move forward, repair or stop.

## Inside a CrewAI stage

`build_crew()` resolves the models, chooses tools, assembles prompt context and
creates two sequential tasks: specialist work, then independent review. Model
selection is in `stage_models()`; prompt wording lives in `prompts.py`.

Only the implementation specialist receives a source-write tool. Document reviewers
judge documents rather than requiring later implementation work to be complete.
The implementation writer and reviewer can run the configured checks, but cannot
choose arbitrary check commands through that tool.

`CandidateProgress` stops repeated unchanged failures. `implementation_guardrail()`
requires passing verify/security evidence for the current source before handoff.
Their terminal signals intentionally inherit from `BaseException`: CrewAI must not
swallow them as ordinary retryable tool errors. `SDLCStageFlow` records those stops
as failures and retains evidence.

## State and evidence to preserve

- `stage` is a zero-based index into `STAGES`; after completion it equals the number
  of stages. Failed and interrupted attempts remain in `attempts`.
- Approval binds source, task, configuration, artifacts and attempt history.
  It is not simply permission to execute a stage name regardless of later changes.
- Changed source after verification returns to verification. Once delivery has
  started, changed source requires reconciliation instead of automatic replay.
- A passed agent review does not replace external verification or installed-copy
  observation. The example adapters use real commands for those stages.
- JSON field names and saved-run formats remain stable. Old run directories do not
  need migration. Schema imports now use their canonical module, as described below.

## Schema import migration

Import stage schemas directly from `ai_pipeline.stage_contracts`:

```python
from ai_pipeline.stage_contracts import DesignDocument, PlanDocument, StageReport
```

The compatibility exports from `ai_pipeline.crewai_adapter` have been removed:
`RequirementsDocument`, `DesignDocument`, `PlanStep`, `PlanDocument`, `StageReport`,
`StageState`, and `DOCUMENTS`. External Python callers using those old paths must
update their imports. This does not change the CLI, prompt text, schema fields,
or persisted run data. The adapter now references the `stage_contracts` module
explicitly instead of exposing the schemas through its own imports.

`DOCUMENT_INSTRUCTIONS` is also no longer re-exported by the adapter; its canonical
location is `ai_pipeline.prompts`.

## Validate a change

```sh
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
```

The suite includes real CrewAI flows with scripted models, approval and digest
invalidation, repair limits, interrupted execution, package tampering, and temporary
loopback HTTP services. It does not need provider keys or paid model calls.

When changing prompts, remember that wording is runtime behavior. The readability
refactor compared all six stages, with and without revision feedback, to confirm
identical agent roles, tool names, task descriptions and expected outputs.
