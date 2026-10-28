# AI Pipeline

A local, project-adaptable SDLC factory using **CrewAI** for agent work and a durable outer engine for evidence and approval gates. A request moves through requirements, design, planning, implementation, verification, security, review, release, deployment, observation, and retrospective. Agent stages execute CrewAI Flows and specialist/reviewer crews; operational stages run configured commands. Every stage records evidence. Verification failures can return to implementation. Release and deployment each require explicit approval.

**Status: validated locally with real CrewAI model calls.** Three frozen CSVJSON trials completed all 11 stages without manual candidate repair or operator retries; each passed 259 scenarios and nine baseline tests before and after local installation. The verified feature was promoted into the target repository. This is evidence for the tested tasks/configurations, not arbitrary-project reliability or production deployment. See the dated results below.

## Public example projects

- [Textstats](https://github.com/adico1/ai_pipeline_first_run): verified word-counting fix.
- [CSVJSON](https://github.com/adico1/csvjson-second-run): promoted delimiter feature, with regression tests.
- [HTTPStats](https://github.com/adico1/httpstats-third-run): promoted `POST /analyze` with opt-in word frequencies, UTF-8 byte counts, and 89 real HTTP regression scenarios and source provenance.

HTTPStats was promoted byte-for-byte from run `dfd4d8e1e18d` in commit `a299ec9`;
all 44 scenarios passed in its normal checkout. CSVJSON's 12 repository tests also
passed before publication. These are public source repositories, not cloud-hosted
services. See [publication and promotion evidence](reports/project-publication-20261028.json).
Historical trial sections below describe their original baselines. HTTPStats and
CSVJSON HEAD now include the completed features; reproducing the missing-feature
trials requires separate checkouts at the recorded baseline commits.

## Code structure

Start with `Factory.advance()` in `ai_pipeline/engine.py` for the lifecycle.
Agent instructions live in `ai_pipeline/prompts.py`; structured deliverables live
in `ai_pipeline/stage_contracts.py`. See the [code-reading guide](docs/code-guide.md)
for the stage flow, module responsibilities and evidence rules. Python callers
should import schemas from `ai_pipeline.stage_contracts`; the old adapter
re-exports were removed. See the guide’s schema import migration section.

## Run locally

Requires Python 3.11–3.13, uv, and Git on macOS or Linux. CrewAI remains pinned to **1.9.3**, tested on this Intel Mac. An isolated resolution check on 2026-10-28 confirmed that the latest published 1.15.32 and newer stable releases cannot resolve with the required Intel macOS support because of LanceDB wheel availability. `uv.lock` records dependencies; `.python-version` selects Python 3.13.

```sh
cd /Users/adicohen/work/ai_pipeline
uv sync --locked
uv run ai-pipeline demo
```

The result contains a run `id`. It stops before design for review. Substitute that ID below:

```sh
uv run ai-pipeline status RUN_ID
uv run ai-pipeline status RUN_ID --json
uv run ai-pipeline approve RUN_ID --actor your-name --note "Reviewed the requirements"
uv run ai-pipeline advance RUN_ID
```

The first implementation deliberately fails independent addition scenarios. The repair loop fixes the code and verifies it again. The run then pauses before release. Review `.factory/RUN_ID/artifacts/`, approve, and advance again. It pauses separately before deployment. Approve and advance once more to finish the **simulated** lifecycle. Approval never automatically executes a stage.

```sh
uv run ai-pipeline list
uv run ai-pipeline metrics
uv run python -m unittest discover -s tests -v
```

`status` now shows a readable summary, evidence paths, approval review guidance and the next command. Use `status RUN_ID --json` for the previous full JSON output (update scripts that parse status). Other commands retain JSON output. Suggested commands preserve the selected state directory and environment-file path. Failed runs require diagnosis before retry; delivery failures require reconciliation.

Use `--state-dir /absolute/path` before the subcommand to keep runs elsewhere. Different run IDs can execute concurrently in separate processes; each individual run has an exclusive lock. There is no background worker or fleet scheduler yet.

## Automated tests

The `Tests` GitHub Actions workflow runs on pushes, pull requests, and manual
workflow dispatch. It uses Ubuntu, the Python version in `.python-version`, uv
0.13.0, and `uv sync --locked`. The suite uses scripted local models and simulated
or temporary local delivery; it needs no provider API keys and makes no paid model
calls. Telemetry is disabled. The workflow has read-only repository permissions
and a 15-minute job timeout.

To reproduce a failure locally:

```sh
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
```

On GitHub, open **Actions → Tests → the failed run → Python 3.13 tests** and inspect
the first failing step. Dependency-install failures are separate from test failures.
The local macOS result and the GitHub Linux result validate their respective
platforms; neither substitutes for a fresh live factory trial.

## Dependency maintenance

Our `PipelineCrew` uses a scoped task-output storage implementation that closes
SQLite connections after every operation, including failures. This addresses the
resource leak in the pinned CrewAI version without editing installed packages or
patching global SQLite behavior. It preserves the existing database table and
record format. The compatibility layer refuses a different CrewAI version until
its storage integration is explicitly reassessed.

CrewAI's internal `Agent.multimodal` deprecation warnings remain visible; the
pipeline does not use that feature or suppress those warnings. The latest inspected
release still accesses it internally. See the [maintenance report](reports/crewai-maintenance-20261028.json)
for resolution results and the [upstream storage fix](https://github.com/crewAIInc/crewAI/pull/7493).
No alpha build, transitive dependency override or platform-specific framework
split was adopted.

## Connect a project

The local `.env` contains empty model/key fields and is excluded from Git. Fill `FACTORY_MODEL` with your provider/model ID and fill that provider's API key. A shareable, key-free template is tracked as `.env.example`.

`FACTORY_OPENAI_DIRECT=true` opts this project into direct OpenAI access at `https://api.openai.com/v1`, overriding inherited gateway URL variables. In this mode, the `.env` OpenAI key takes precedence over a shell key, including when the file's key is blank. This affects only the CLI and its child processes; it does not edit global shell settings. Set it to false to retain inherited routing.

The CLI loads `.env` from the current directory before running commands; existing shell variables take precedence. For another location, use `uv run ai-pipeline --env-file /absolute/path/to/settings.env ...`. Settings are inherited by CrewAI subprocesses even though they execute in isolated worktrees. The `.env` file itself is not copied into candidate repositories.

Optional `FACTORY_MODEL_REQUIREMENTS`, `FACTORY_MODEL_DESIGN`, `FACTORY_MODEL_PLAN`, `FACTORY_MODEL_IMPLEMENT`, `FACTORY_MODEL_REVIEW`, and `FACTORY_MODEL_RETROSPECTIVE` select specialist models per stage. `FACTORY_REVIEW_MODEL` selects the second reviewer agent's model across all stages. Blank overrides fall back to the default/specialist model. Explicit `crewai.model` and `crewai.review_model` in project configuration take precedence over environment model settings. Do not put API keys in project configuration.

```sh
uv run ai-pipeline init --repository /absolute/path/to/repo --output factory.json
```

The generated configuration uses `backend: "crewai"` for requirements, design, plan, implement, review, and retrospective. Set a CrewAI-supported model with `--model`, the stage's `crewai.model`, or `FACTORY_MODEL`. Supply provider credentials through the runtime environment, never through project JSON. See [CrewAI provider configuration](https://docs.crewai.com/en/concepts/llms); provider availability depends on the pinned framework version and optional dependencies.

Fill the `command` arrays for verify, security, release, deploy, and observe. These stages cannot use the CrewAI backend; model judgments cannot substitute for executable checks or deployment receipts. Empty commands deliberately fail validation rather than silently skipping work. Commands are argument lists, not shell snippets. Use absolute executable and adapter paths because commands execute inside the candidate workspace.

```sh
uv run ai-pipeline create --config factory.json --task "Describe the desired behavior and acceptance criteria"
uv run ai-pipeline advance RUN_ID
```

A real run creates a detached Git worktree from the repository's committed HEAD. Uncommitted changes are not copied. The original working directory remains separate. Runs retain worktrees and artifacts for review; clean them up with Git's worktree removal command after preserving needed work. The factory does not commit, push, open pull requests, merge, or deploy unless you explicitly configure adapters that do so.

## CrewAI execution

### First real target: Textstats

The separate local Git repository `/Users/adicohen/work/ai_pipeline_first_run` contains a text-statistics CLI with a deliberate word-counting bug. Its baseline fails 12 of 16 external checks. `projects/textstats.json` connects it to CrewAI and the trusted adapters in `integrations/textstats/`.

Verification exercises stdin and file input, empty/whitespace-only text, Unicode separators, repeated spaces, and line endings. The security adapter is a limited static policy check, not a full audit. After human approvals, release creates a ZIP and digest manifest; deployment installs the verified script in a separate artifact directory; observation checks that installed copy. No cloud hosting or network listener is involved. The paths in this configuration are specific to this machine.

Once your factory `.env` has a model and matching key, use `uv run ai-pipeline list` to find the queued `textstats-first-run`, then `uv run ai-pipeline advance RUN_ID`. This begins real model calls and pauses at the configured approval gates. The target repository intentionally remains unfixed until the agent works in its candidate worktree.

`SDLCStageFlow` prepares context, executes a sequential crew, and saves a validated result. A specialist completes the stage; a second agent reviews it and returns `passed` or `blocked`. Blocked reports fail the stage. Prior reports and verification failures are carried into subsequent prompts. Each attempt saves `crew-report.md`, `token-usage.json`, and `result.json`.

Requirements also produce `requirements.json` with objective, scope, measurable acceptance criteria, constraints, and open questions. Requirements/design/plan reviewers evaluate documents without source-code tools. Only successful upstream stages are carried forward as accepted context; failed attempts remain in the audit history. Implementation separately receives the latest failure as repair feedback. This prevents a retry from treating an earlier mistaken implementation judgment as a requirement to finish coding before planning.

Design and planning similarly produce validated `design.json` and `plan.json`. Design records the approach, interfaces, data flow, decisions/tradeoffs, edge cases, and verification strategy. Planning records ordered actions with targets and completion criteria, verification steps, and risks. The full documents are passed to downstream agents; a list of bugs alone cannot satisfy these document contracts.

Rejected documents, final reviews, and retrospectives receive up to two automatic revisions within the same stage timeout. The writer receives the rejected deliverable and concrete review feedback; every review round is saved. Exhausted revisions still fail the stage. Final code review receives a bounded snapshot of the currently changed tracked source so it can distinguish the repaired code from historical bug descriptions.

Only the implementation specialist receives a file-write tool. Other specialists and all reviewers receive source read/list tools. Tools reject path traversal, symlinks, and sensitive paths and cap file size. Agents have no shell or deployment tool. The implementation can write any source language; project commands compile, test, and deliver it. These restrictions do not constitute an OS sandbox.

Implementation agents and their reviewers also have `check_current_candidate`, a no-argument tool that runs only the operator-configured verify/security commands against the current candidate. Each call saves its own reports under the implementation attempt. The model cannot choose arbitrary commands. These checks provide repair feedback; the independent verify/security stages still rerun afterward and remain the release gates.

The durable ledger, repair loop, and human approval gates remain outside CrewAI. Each agent stage uses a fresh Flow; lifecycle resume uses the factory ledger. Crew memory, caching, telemetry, and tracing are disabled by default. Live model calls send the task, prior reports, and selected source to your configured provider. Limits are 12 agent iterations, one agent retry, and the outer stage timeout; monetary budgets are not implemented.

Tests execute the actual CrewAI Flow, Crew, Agent, Task, structured-report conversion, and tools with a scripted local `BaseLLM`. This validates framework integration without making remote model calls; it does not validate reasoning quality or provider credentials. The original simulated full-lifecycle tests remain in place.

## Stage contract

| Stage | Required project behavior |
|---|---|
| requirements | Turn intent into scope, acceptance criteria, constraints, and unresolved questions |
| design | Produce architecture, interfaces, risks, and decisions |
| plan | Produce an ordered implementation and verification plan |
| implement | Invoke your coding agent or implementation tool against the candidate workspace |
| verify | Run independent behavior checks against the actual candidate and relevant dependencies |
| security | Run configured vulnerability, policy, or other security checks |
| review | Produce a change summary and an evidence-based review |
| release | After approval, package/publish an immutable candidate with its manifest |
| deploy | After separate approval, deploy the verified artifact and record its identity and rollback reference |
| observe | Check the deployed revision and record health/incident evidence |
| retrospective | Record outcomes and proposed follow-up work |

The default additional gate is before `design`, allowing requirements review. Configure `gates` to add pauses before any stage. For example, a gate before `plan` allows review of the completed design. Release and deploy gates cannot be disabled through configuration.

Each adapter receives:

- `FACTORY_CONTEXT`: path to JSON containing the task, stage, run ID, workspace, artifact root, output directory, base commit, and previous attempt.
- `FACTORY_OUTPUT`: directory for the current attempt's reports and results.
- Working directory: the isolated candidate source tree.

Successful adapters must exit zero and write `result.json` to `FACTORY_OUTPUT`:

```json
{
  "status": "passed",
  "summary": "Four checkout scenarios passed against candidate revision …",
  "reports": ["scenarios.json"],
  "artifact_digest": "optional project-defined artifact identity"
}
```

Write detailed reports alongside the result. A failure must return a nonzero exit code or a non-passed result. Missing output is a failure. The engine stores stdout, stderr, context, duration, source fingerprints, and results for each attempt. A summary alone is not proof: the quality of checks is the project operator's responsibility.

`ai_pipeline/command_adapter.py` wraps existing commands that communicate success through exit status. For example, a stage command can be:

```json
[
  "/absolute/path/to/python3",
  "/Users/adicohen/work/ai_pipeline/ai_pipeline/command_adapter.py",
  "--summary", "Project unit tests completed",
  "--", "/absolute/path/to/python3", "-m", "unittest", "discover", "-s", "tests"
]
```

That check does not replace integration or acceptance scenarios. Custom command adapters can also read `FACTORY_CONTEXT`. CrewAI is the default agent backend; provider credentials stay outside project configuration. Do not use an agent's self-reported success as the verification stage.

## Evidence and failure semantics

- Verification is tied to a SHA-256 source-tree fingerprint. Untracked files are included. `.git`, caches, virtual environments, and `node_modules` are excluded; dependency/environment provenance must be captured by project adapters.
- Verification and later stages must leave source unchanged; reports/build outputs belong outside source. Changes before delivery invalidate verification and approvals and restart at verification.
- Source changes after a release/deploy attempt stop the run for reconciliation. They never automatically replay delivery.
- Approvals bind to source, task, configuration, recorded attempts, and artifact contents. They are local operator attestations, not authenticated multi-user authorization or cryptographic signatures.
- Configuration and task snapshots cannot change within a run. Start a new run for changed scope or policy.
- Failed verification/security can trigger up to `max_repairs` implementation attempts (default 2, maximum 5). Adapters have individual timeouts (default 300 seconds, maximum 3600).
- Failed or interrupted non-delivery stages require `retry RUN_ID`, then `advance RUN_ID`. Inspect side effects first. Interrupted attempts retain their directories.
- Failed/interrupted release or deploy is never retried by this engine. Reconcile externally before creating another run. Adapters must implement idempotency using `run_id`, immutable artifacts, and receipts.
- Metrics include real local attempt counts and verification duration. Escape rate remains unknown until actual production incidents are attributed. Demo results are labeled and must not be treated as production measurements.

## Fresh-run validation — 2026-10-28

Run `df6db6c2e034` completed all 11 stages with factory commit `219605d`
and the existing `openai/gpt-4o-mini` configuration. It started from the original
Textstats bug at `e47446a7f52f8c929dc58876c11211fb2a9ac19a`, using a local clone
and the original task and acceptance checks. The published repository was not
changed by this validation.

| Evidence | Result |
| --- | --- |
| Factory test suite | 39 tests passed |
| Original buggy CLI baseline | 4/16 scenarios passed |
| Independent candidate verification | 16/16 passed |
| Configured static security policy | Passed (limited import/execution checks) |
| Local ZIP | Manifest hashes checked; packaged bytes matched verified source |
| Installed-copy observation | 16/16 passed |
| Stage attempts | 11, all passed |
| Operator retries / manual candidate edits | 0 / 0 |
| Engine repair cycles / document review revisions | 0 / 0 |
| Approval gates | 3 evidence reviews performed by Codex under user authorization |
| Active stage execution / elapsed run time | 117.384 seconds / 187.063 seconds |
| CrewAI-reported usage | 154,808 tokens: 146,550 prompt + 8,258 completion; 54 requests |

Usage is framework-reported, not a billing statement. Approval gates were retained;
this was not an approval-free run. Local evidence is retained under
`.factory/df6db6c2e034/`, with the summary in `.factory/stabilization.json`.

Three preceding validation trials stopped before delivery and exposed review
grounding and document revision issues. Those led to committed factory fixes;
the successful run above started fresh after the fixes, without candidate edits
or operator retries. This establishes one successful clean run, not a general
reliability rate across projects.

To inspect this result and repeat the factory tests on this machine:

```sh
cd /Users/adicohen/work/ai_pipeline
uv run ai-pipeline status df6db6c2e034
.venv/bin/python -m unittest discover -s tests -v
git log -1 --oneline
```

## Second task: optional pretty JSON — 2026-10-28

Fresh run `859c7d2e0900` completed all 11 stages on its first attempt using
CrewAI and the existing model configuration. It added `--pretty` to Textstats
from base commit `e0cf86b0e570a4a61cc29d9d22872640c92530f5`.
Factory/checks commit: `273ce1c`. The scope and acceptance checks were committed
before execution; the task is in `projects/textstats-pretty-task.txt` and the
configuration is `projects/textstats-pretty.json`.

- All 42 factory tests passed, including checks that detect missing/ignored
  pretty formatting and unwanted changes to default formatting.
- Baseline: 16/16 default-output scenarios passed; 0/24 pretty-output scenarios
  passed. Candidate and installed copy: **40/40 passed** each.
- Scenarios cover eight text inputs, stdin and file input, unchanged default
  output, exact two-space JSON indentation, and the flag before/after a file.
- Security policy, source review, ZIP manifest verification, local installation,
  observation and retrospective passed. Counts and default output were preserved.
- Zero operator retries, manual candidate edits, engine repair cycles or review
  revisions. Three existing approval gates were reviewed by Codex under user
  authorization.
- Active stage time: 115.171 seconds; elapsed run time: 179.805 seconds.
- CrewAI-reported usage: 163,890 tokens (154,842 prompt + 9,048 completion),
  38 requests. This is not a billing statement.

The generated feature is delivered in the run's local ZIP and installed copy;
the original repository checkout and public GitHub release are unchanged.
The source change was made by the factory, without operator code repair.

Inspect the result and try the installed feature:

```sh
cd /Users/adicohen/work/ai_pipeline
uv run ai-pipeline status 859c7d2e0900
printf 'hello world\n' | .venv/bin/python .factory/859c7d2e0900/artifacts/009-deploy-84dfa25f/installed/textstats.py --pretty
```

To create another run of this same bounded task:

```sh
uv run ai-pipeline create --config projects/textstats-pretty.json --task "$(cat projects/textstats-pretty-task.txt)"
# Use the returned run ID with advance; review each approval gate before approving.
```

## Second repository: CSVJSON delimiter trial — 2026-10-28

The CSVJSON integration was committed as `90f1452`. It uses the existing CrewAI
model and engine, project-specific checks and local delivery adapters in
`integrations/csvjson/`, configuration `projects/csvjson.json`, and task
`projects/csvjson-task.txt`. The target baseline is commit
`c43bfa62a1f2d28a10cf00e3f31987a4c5547b8f` in the sibling `csvjson-second-run`
repository. All **46 factory tests passed** before execution.

Run `dcaed973ea27` **failed at implementation**. Requirements, design and planning
passed; the original implementation attempt and two operator retries failed.
The candidate was never edited manually, and no release, deployment or installed
observation occurred. This trial does **not** meet the completion criteria.

The independent suite contains 154 CLI scenarios. Baseline: 99/154 passed, with
all 55 successful explicit-delimiter scenarios failing. Some invalid-delimiter
scenarios pass on the baseline because the option itself is unsupported; the
aggregate baseline number alone is therefore not evidence of feature support.
The final candidate passed 141/154 scenarios and all nine original baseline
tests, rerun from an external snapshot. Remaining failures: backslash is rejected
despite being allowed, while `Z`, `0`, `é` and fullwidth semicolon `；` are accepted
despite being invalid (the latter four each fail in three input/option modes).
The ordinary ASCII semicolon is valid and is not one of these remaining failures.

Evidence is retained in `.factory/dcaed973ea27/`. The last advisory check is
`artifacts/006-implement-3f6a5f06/candidate-checks/verify-9571fc6a/result.json`.
These are implementation-time checks, not a passed external verification stage.
The source repository's main checkout is unchanged.

- Active stage time: 520.183 seconds; elapsed run time: 593.057 seconds.
- CrewAI-reported usage: 1,974,108 tokens (1,947,864 prompt + 26,244 completion),
  114 requests. This is not a billing statement.
- One requirements approval was reviewed under user authorization. Retry clears
  active approvals; approval history remains in the event log.
- Repeated checks plateaued without correcting the validation logic. Before
  another trial, investigate concise failure feedback and detection of unchanged
  failed candidates; do not weaken acceptance criteria or count manual repair as
  autonomous success.

Inspect this trial and rerun the factory tests:

```sh
cd /Users/adicohen/work/ai_pipeline
uv run ai-pipeline status dcaed973ea27
.venv/bin/python -m unittest discover -s tests -v
```

## Bounded implementation feedback

The implementation check tool now groups duplicate failed cases across input
modes and returns at most eight representative groups, with bounded text and
expected/actual values. Full command results remain in `candidate-checks/`;
`latest-candidate-feedback.json` retains the compact report. Large external
verification failures are also compacted when handed to a repair attempt.

Within an implementation attempt, the first repeated check of unchanged failing
source reuses existing evidence and warns the agent. Another unchanged request
stops the attempt. Three checked candidates with identical failure results also
stop it, even if their source bytes changed. A different result resets that
counter. The reviewer independently reruns checks and does not contribute to the
writer's repetition counter. External verification and security still run after
implementation passes.

The stop signal cannot be swallowed as an ordinary retryable CrewAI tool error;
the flow records a failed stage with `stop_reason: no_progress` and a
`no-progress.json` artifact. No automatic operator retry follows that stop.
Interrupted CrewAI usage totals are marked unavailable, not zero. Each fresh
stage attempt gets a new progress counter; this is not a cross-run rate limiter.

## Feedback improvements and fresh trials — 2026-10-28

Commits `a305d30` and `e5a8125` add compact feedback, deterministic no-progress
stops, and explicit review of general input-validation rules. **52 factory tests
pass**, including a real CrewAI tool-loop test that confirms no-progress ends
the attempt with a failed result. The model and target baseline remain unchanged.

The first fresh trial, `5bf93154f231`, passed the original 154 scenarios but was
**not approved for release**. Operator source review found hard-coded failing
test values instead of a general ASCII punctuation predicate. An expanded audit
found 63 failures (196/259 passed). Its state remains `awaiting_approval` at release;
`operator-review.json` records why approval was withheld. Do not approve this run.

The independent suite now has 259 scenarios. It includes invalid delimiters
with empty input so malformed CSV cannot masquerade as option validation. It
checks every non-NUL ASCII character outside the allowed category, plus empty,
multicharacter and diverse non-ASCII values. NUL cannot be passed as a process
argument. Original CSV behavior and valid punctuation checks remain intact.

The subsequent fresh trial, **`51c8a1f85810`, failed at implementation**:

- Requirements, design and planning passed with no revisions.
- Last implementation-time checks: **215/259 scenarios**, all nine original
  baseline tests passed. Forty-four delimiter scenarios still failed.
- Zero manual candidate edits and zero operator retries. No release, deployment
  or installed observation occurred.
- The no-progress guard did not trigger: failures changed between revisions.
  The normal bounded implementation/reviewer cycle ended with a blocked verdict.
- Active stage time: 210.938 seconds; elapsed run time: 239.211 seconds.
- CrewAI-reported usage: 229,082 tokens (219,462 prompt + 9,620 completion),
  42 requests. These are not billed-cost figures or a controlled benchmark.
- The final compact feedback file is 4,275 bytes versus 11,323 bytes for the
  underlying result files. Full evidence is retained.

This validates the feedback/stop controls and exposes a remaining model behavior:
adding individual exclusions instead of enforcing the general rule. It does not
establish successful autonomous delivery on the second repository. Further trials
should address that behavior rather than weaken checks or repeat the same run.

```sh
cd /Users/adicohen/work/ai_pipeline
uv run ai-pipeline status 51c8a1f85810
.venv/bin/python -m unittest discover -s tests -v
```

## Controlled implementation-model trial — 2026-10-28

Configuration commit `aea2a3f` adds
`projects/csvjson-strong-implementation.json`. Relative to the previous trial,
only implementation model routing changes: the writer uses
`openai/gpt-4.1-2025-04-14`; its reviewer explicitly remains
`openai/gpt-4o-mini`. All other stage configuration, the task, baseline, 259
acceptance scenarios, nine original tests and stop controls are unchanged.
The adapter's constructed models and saved run context confirmed this routing.
The model supports the existing Chat Completions, tool-calling and structured
output interface ([official model documentation](https://developers.openai.com/api/docs/models/gpt-4.1)).
All **52 factory tests passed** before execution.

The one authorized fresh trial, **`77a35451dc69`, failed at implementation**.
Requirements, design and planning passed. The implementation writer returned an
assessment of missing delimiter support rather than editing source; identical
before/after source digests confirm that the candidate remained at baseline.
The reviewer correctly blocked it. There were zero operator retries, zero manual
candidate edits, no release and no deployment. The no-progress guard did not
trigger; the writer and reviewer each checked the unchanged source once.

| Measurement | Previous GPT-4o-mini writer | GPT-4.1 writer trial |
| --- | --- | --- |
| Run | `51c8a1f85810` | `77a35451dc69` |
| Last advisory acceptance results | 215/259 | 204/259 (unchanged baseline) |
| Original baseline tests | 9 passed | 9 passed |
| Implementation-stage seconds | 168.260 | 62.688 |
| Implementation crew tokens (writer + reviewer) | 200,850 | 24,501 |
| Total active stage seconds | 210.938 | 103.321 |
| Elapsed run seconds | 239.211 | 137.409 |
| Total reported tokens | 229,082 | 53,051 |
| Total reported requests | 42 | 18 |

The current total consists of 48,405 prompt tokens and 4,646 completion tokens.
These are CrewAI-reported usage totals, not billed cost. Fewer tokens and less
time do not indicate success: the stronger writer performed no implementation.
This single trial does not establish whether model capability is the bottleneck.
The next investigation should focus on why the implementation task accepted an
assessment as the writer's final deliverable, before another paid comparison.

```sh
cd /Users/adicohen/work/ai_pipeline
uv run ai-pipeline status 77a35451dc69
.venv/bin/python -m unittest discover -s tests -v
```

## Implementation handoff contract

The writer's deliverable is working source, not an assessment or proposed next
steps. Before the writer can hand off to the reviewer, a deterministic CrewAI
task guardrail requires passing configured verify/security checks for the current
source digest. Missing or stale evidence causes fresh checks. A narrative claim
cannot substitute for those results, and an already-correct candidate need not
be edited merely to satisfy the contract.

One rejected handoff is returned to the same writer with explicit instructions
to edit source and check it. A second incomplete handoff stops with
`stop_reason: implementation_incomplete`; it does not proceed to review. The
existing no-progress controls remain active across this bounded correction.
`implementation-handoff.jsonl` records each decision and its evidence. Independent
review and external verification still follow a successful writer handoff.

Network-free tests exercise the actual CrewAI path for an assessment followed
by a tool-written correction, an assessment-only writer stopped after one
correction, and rejection of stale passing evidence after a source change.

## Successful CSVJSON delivery after handoff fix — 2026-10-28

Fresh run **`6b760521d51f` completed all 11 stages** using factory commit
`8db0192` and the same GPT-4.1 writer / GPT-4o-mini reviewer configuration as the
previous model trial. It started from CSVJSON baseline
`c43bfa62a1f2d28a10cf00e3f31987a4c5547b8f`. The task and independent checks were
unchanged. All **55 factory tests passed** before execution.

The writer implemented a general delimiter predicate using `string.punctuation`,
a single-character requirement, double-quote exclusion and an ASCII range check.
Operator source review confirmed this was not a list of test-specific exclusions.
The writer corrected an intermediate syntax failure during its own implementation
work. Its first final handoff passed the new deterministic contract, so no handoff
correction was needed in this live run. Network-free CrewAI tests cover the
rejected-handoff correction path; one live success does not isolate which prompt
or contract change caused the improvement.

| Evidence | Result |
| --- | --- |
| Independent candidate CLI scenarios | 259/259 passed |
| External original baseline tests | 9/9 passed |
| Security policy and source review | Passed |
| ZIP and manifest | Both hashes recomputed; packaged source matches verified candidate |
| Installed-copy CLI scenarios / baseline tests | 259/259 and 9/9 passed |
| Operator retries / manual candidate edits | 0 / 0 |
| Engine repair cycles / handoff rejections | 0 / 0 |
| Existing approval gates | 3 evidence reviews under user authorization |
| Active stage time / elapsed run time | 239.757 / 292.380 seconds |
| CrewAI-reported tokens / requests | 157,359 / 38 |

Reported usage comprises 148,011 prompt and 9,348 completion tokens; it is not a
billing statement. This includes delivery/retrospective stages that failed trials
never reached. The candidate was delivered as a local ZIP and separate installed
copy. The original repository checkout and public hosting were not changed.

Inspect and try the delivered CLI:

```sh
cd /Users/adicohen/work/ai_pipeline
uv run ai-pipeline status 6b760521d51f
printf 'name;count\nAda;007\n' | .venv/bin/python .factory/6b760521d51f/artifacts/009-deploy-3043ec3a/installed/csvjson.py --delimiter ';'
```

## Three frozen repeatability trials and promotion — 2026-10-28

**All three fresh CSVJSON trials completed all 11 stages.** Factory commit
`d8595dd8a7d0ac143afb8d9cb049ad74eba57629`, tracked file hashes, task,
configuration, model settings and target baseline were frozen and checked across
the experiment. The original baseline remained
`c43bfa62a1f2d28a10cf00e3f31987a4c5547b8f` until all trials finished.
The writer was GPT-4.1 (`2025-04-14` snapshot); its reviewer and other AI stages
remained GPT-4o-mini. Preflight: **55 factory tests passed**.

| Trial | Run | Active stage seconds | Elapsed seconds | Reported tokens | Outcome |
| --- | --- | --- | --- | --- | --- |
| 1 | `4c1927a4ae2a` | 231.523 | 298.131 | 112,534 | Completed |
| 2 | `9bf99ee9cc81` | 228.917 | 299.011 | 112,061 | Completed |
| 3 | `5e9f8473078c` | 232.525 | 284.872 | 126,003 | Completed |

Each candidate and installed copy passed **259 independent CLI scenarios and
nine original baseline tests**. Every trial had zero operator retries, manual
candidate repairs and engine repair cycles. Three approval gates per trial were
reviewed under user authorization. No early stop was needed. Total reported usage:
**350,598 tokens**; mean active stage time: **230.988 seconds**. Token totals are
not billed cost, and elapsed time includes evidence-review waits.

Source review checked the full delimiter rule, not just passing examples. Trial
2's model-written review prematurely mentioned installed checks; that claim was
not used as approval evidence, and actual installed-copy checks ran subsequently.
This reinforces the need for independent command evidence and review gates.

After all three succeeded, trial 1's exact verified source bytes were promoted
into `/Users/adicohen/work/csvjson-second-run`, committed as **`d23e72a`**, with
usage documentation, a semicolon example and delimiter regression tests. The
promoted repository passed **12 test methods and all 259 independent scenarios**.
Promotion did not manually repair or rewrite the generated source. No public
release or hosted service was created.

The machine-readable comparison is
[`reports/csvjson-repeatability-20261028.json`](reports/csvjson-repeatability-20261028.json).
The local full frozen manifest remains in
`.factory/csvjson-repeatability-20261028.json`. Three successes are evidence for
this task and configuration, not a general reliability guarantee across projects.
Future runs against the repository HEAD now start from the promoted feature;
repeating the original experiment requires the recorded baseline commit.

Try the promoted feature directly:

```sh
cd /Users/adicohen/work/csvjson-second-run
python3 csvjson.py examples/people-semicolon.csv --delimiter ';'
python3 -m unittest discover -s tests -v
git log -1 --oneline
```

## HTTP-service trial setup — 2026-10-28

The third target is `/Users/adicohen/work/httpstats-third-run`, a standard-library
Python HTTP service with a working `GET /health` baseline (commit `9fa3c58`).
The bounded task in `projects/httpstats-task.txt` adds `POST /analyze`. The
configuration is `projects/httpstats.json`; the implementation writer remains
GPT-4.1 with GPT-4o-mini review and other AI stages. The first fresh live trial completed successfully; see the result below.

The independent sensor in `integrations/httpstats/` starts a real process on an
ephemeral loopback port, exercises 44 HTTP cases (including three baseline health
and unknown-path cases), and always terminates the process. It covers Unicode,
empty/whitespace input, line endings, malformed bodies, invalid text types,
unsupported methods, and health after errors. Release/deploy use a ZIP and SHA-256
manifest; observe repeats the HTTP suite against the separately installed bytes.
These are temporary local services, not persistent or cloud deployments.

Five integration tests establish that the sensor rejects the missing-feature
baseline and incorrect implementations, accepts a test-only reference, detects
package/installed tampering, and stops services even when checks raise. The
reference is never copied into a factory candidate. Running these tests requires
permission to bind loopback ports.

```sh
uv run ai-pipeline create --config projects/httpstats.json --task "$(cat projects/httpstats-task.txt)"
# Use the returned ID; review each gate before approving.
uv run ai-pipeline advance RUN_ID
```

## HTTP-service trial result — 2026-10-28

Run `dfd4d8e1e18d` completed all 11 stages from baseline `9fa3c58`, using factory
commit `8eadee8`. All **68 factory tests passed**, and the [integration CI run](https://github.com/adico1/ai_pipeline/actions/runs/40692697150)
passed on GitHub. Frozen task, configuration and tracked factory hashes were
verified unchanged throughout the trial.

- Candidate and separately installed service: **44/44 real HTTP checks each**, including three baseline checks.
- Zero operator retries, manual candidate edits or engine repair cycles.
- Three approval gates reviewed by Codex under user authorization.
- Only `server.py` changed. Source review confirmed the general Unicode counting
  formulas and request validation; ZIP and installed hashes matched the candidate.
- Active stage time: 111.908 seconds; elapsed: 151.817 seconds.
- Framework-reported tokens: 98,309; requests: 22.
  Usage is not billed cost, and elapsed time includes review waits.

The source baseline remains unchanged. The feature is delivered in the run ZIP
and installed artifact, not promoted into the baseline or publicly hosted. The
checker stops each temporary service. This is one local HTTP success, not a
production or arbitrary-project reliability guarantee. Adversarial HTTP framing,
request limits and concurrency were out of scope.

[Machine-readable result](reports/httpstats-trial-20261028.json).
To inspect the run and start the delivered service yourself:

```sh
cd /Users/adicohen/work/ai_pipeline
uv run ai-pipeline status dfd4d8e1e18d
.venv/bin/python .factory/dfd4d8e1e18d/artifacts/009-deploy-c4a1eedd/installed/server.py --port 8000
```

In another terminal:

```sh
curl -X POST http://127.0.0.1:8000/analyze -H 'Content-Type: application/json' -d '{"text":"hello world"}'
```

Expected counts: `characters: 11`, `words: 2`, `lines: 1`. Stop the server with Ctrl-C.

## Trust boundary and production roadmap

This version runs **trusted adapters with the current user's host permissions and environment**. Git worktrees isolate file changes; they are not security sandboxes. External acceptance files, state, and approvals are not access-controlled against a malicious adapter on the same host. Detection of unexpected source changes is not prevention. No claim of tamper-proof verification is made.

For production use, move implementation into disposable containers/VMs with scoped credentials; run acceptance suites in a separate verification service whose policy and fixtures the coding agent cannot modify. Record image/dependency digests, target environment, artifact provenance, and scenario versions. Use authenticated approval identities and protected storage. Bind deploy operations to artifact digests, not mutable branches.

The next infrastructure layers are a durable worker queue with leases and capacity limits, additional provider integrations and cost budgets, per-change runtime environments, a Git-host review/merge integration, deployment and rollback adapters, and production telemetry that creates follow-up tasks. Observation and retrospective stages currently record adapter output; they do not automatically ingest incidents or enqueue new work.

For a small application, verification may use a local runtime and real test database. Distributed systems need isolated routing or per-change environments and cross-service scenarios. Embedded, mobile, data, and infrastructure projects require their own execution targets. The orchestration contract can be reused across those projects; their sensors cannot be assumed interchangeable.

Inspired by [Building an agentic software factory? Start with the sensor](https://thenewstack.io/agentic-software-factory-sensor/).

### Ongoing HTTPStats development: optional word frequencies

This bounded feature starts from the published HTTPStats analyze implementation.
`projects/httpstats-word-frequencies-task.txt` defines a strict opt-in boolean:
existing responses remain unchanged; enabled requests also return case-sensitive
counts of whitespace-delimited tokens. No dependencies or new routes are needed.
The independent sensor preserves all 44 existing scenarios and adds 19 cases.

```sh
uv run ai-pipeline create --config projects/httpstats-word-frequencies.json --task "$(cat projects/httpstats-word-frequencies-task.txt)"
uv run ai-pipeline advance RUN_ID
uv run ai-pipeline status RUN_ID
```

At each approval gate, inspect its artifacts and approve with an actor and a
specific evidence note, then advance again. The CrewAI team owns candidate
implementation; the operator owns acceptance checks and evidence review.

Run **`d6a512cbd7e3` completed all 11 stages**, starting from published target
commit `a299ec9`. Candidate and installed-copy verification each passed 63/63
scenarios, including all 44 existing scenarios. There were zero operator retries,
manual candidate edits, or engine repair cycles. Codex reviewed three gates;
CrewAI wrote the feature and usage example. The exact verified source was promoted
to HTTPStats commit `2da1271` and its packaged 63-case regression suite passed.
The factory suite passed 74 tests. Active execution took 161.77 seconds; total
elapsed time was 221.742 seconds. CrewAI reported 149,145 tokens across 29 requests.
This was local deployment, with temporary services stopped after observation.

[Machine-readable evidence](reports/httpstats-word-frequencies-20261028.json).

### Ongoing development: optional UTF-8 byte count

This trial builds on the published word-frequency feature. Its strict boolean
`include_utf8_bytes` opt-in adds the byte length of the text encoded as UTF-8,
independent of JSON escaping. It composes with word frequencies and preserves all
63 previous scenarios. The independent sensor adds 26 cases, including Unicode,
invalid flags, and safe rejection of unpaired surrogates when enabled.

```sh
uv run ai-pipeline create --config projects/httpstats-utf8-bytes.json --task "$(cat projects/httpstats-utf8-bytes-task.txt)"
uv run ai-pipeline advance RUN_ID
uv run ai-pipeline status RUN_ID
```

Review and approve each evidence gate before advancing. CrewAI owns candidate
implementation; the operator owns the independent contract and evidence review.

Run **`47dcad718a5c` completed all 11 stages** from published target `2da1271`.
Candidate and installed-copy verification each passed 89/89 scenarios, including
all 63 existing scenarios. The factory suite passed 77 tests. The exact generated
source was promoted as HTTPStats commit `f0120f3`; the promoted suite also passed.

This was **an assisted success**, not an unattended success. First run
`42ffe90fe4c4` was withheld at release because required README changes were missing,
despite the reviewer claiming otherwise. A documentation sensor was added before
the second run. That run then required two operator-directed CrewAI documentation
correction attempts: the first claimed success without editing; a concrete failing
check prompted the second to fix the byte-count example and remove premature
provenance claims. Source bytes stayed unchanged during both corrections.
Verification, security policy and review were rerun after the README changed.
Codex wrote no candidate implementation and reviewed three approval gates.

[Completed-run evidence](reports/httpstats-utf8-bytes-20261028.json) and
[withheld-run evidence](reports/httpstats-utf8-withheld-20261028.json).

### Saved analysis history trial

`projects/httpstats-history.json` starts from the published HTTPStats version with
word frequencies and UTF-8 byte counts. The bounded feature adds SQLite-backed
`POST /analyses` and `GET /analyses/{id}`, leaving `/analyze` stateless.
The independent suite retains 89 earlier scenarios, adds 30 persistence/API checks,
and executes two save/retrieve examples from a declarative README block plus a
startup-documentation check. Database files stay local and outside release ZIPs.

```sh
uv run ai-pipeline create --config projects/httpstats-history.json --task "$(cat projects/httpstats-history-task.txt)"
uv run ai-pipeline advance RUN_ID
uv run ai-pipeline status RUN_ID
```

Review requirements, verified source and release evidence at the approval gates.
CrewAI writes the candidate; acceptance sensors and test-only reference fixtures
are operator-owned and are never copied into candidate implementation.
