# AI Pipeline

A local, project-adaptable SDLC factory using **CrewAI** for agent work and a durable outer engine for evidence and approval gates. A request moves through requirements, design, planning, implementation, verification, security, review, release, deployment, observation, and retrospective. Agent stages execute CrewAI Flows and specialist/reviewer crews; operational stages run configured commands. Every stage records evidence. Verification failures can return to implementation. Release and deployment each require explicit approval.

**Status: CrewAI integration implemented and tested locally; live model execution is not yet validated.** Configure a model/provider and project commands for real work. The separate demo still uses deterministic scripts and simulated delivery. No paid model call or production deployment has been performed. The engine is language agnostic; verification is necessarily project specific.

## Run locally

Requires Python 3.11–3.13, uv, and Git on macOS or Linux. CrewAI is pinned to **1.9.3**, tested on this Intel Mac. Newer CrewAI 1.15 releases require a LanceDB dependency without a compatible Intel macOS wheel. `uv.lock` records dependencies; `.python-version` selects Python 3.13.

```sh
cd /Users/adicohen/work/ai_pipeline
uv sync --locked
uv run ai-pipeline demo
```

The result contains a run `id`. It stops before design for review. Substitute that ID below:

```sh
uv run ai-pipeline status RUN_ID
uv run ai-pipeline approve RUN_ID --actor your-name --note "Reviewed the requirements"
uv run ai-pipeline advance RUN_ID
```

The first implementation deliberately fails independent addition scenarios. The repair loop fixes the code and verifies it again. The run then pauses before release. Review `.factory/RUN_ID/artifacts/`, approve, and advance again. It pauses separately before deployment. Approve and advance once more to finish the **simulated** lifecycle. Approval never automatically executes a stage.

```sh
uv run ai-pipeline list
uv run ai-pipeline metrics
uv run python -m unittest discover -s tests -v
```

Use `--state-dir /absolute/path` before the subcommand to keep runs elsewhere. Different run IDs can execute concurrently in separate processes; each individual run has an exclusive lock. There is no background worker or fleet scheduler yet.

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

## Trust boundary and production roadmap

This version runs **trusted adapters with the current user's host permissions and environment**. Git worktrees isolate file changes; they are not security sandboxes. External acceptance files, state, and approvals are not access-controlled against a malicious adapter on the same host. Detection of unexpected source changes is not prevention. No claim of tamper-proof verification is made.

For production use, move implementation into disposable containers/VMs with scoped credentials; run acceptance suites in a separate verification service whose policy and fixtures the coding agent cannot modify. Record image/dependency digests, target environment, artifact provenance, and scenario versions. Use authenticated approval identities and protected storage. Bind deploy operations to artifact digests, not mutable branches.

The next infrastructure layers are a durable worker queue with leases and capacity limits, additional provider integrations and cost budgets, per-change runtime environments, a Git-host review/merge integration, deployment and rollback adapters, and production telemetry that creates follow-up tasks. Observation and retrospective stages currently record adapter output; they do not automatically ingest incidents or enqueue new work.

For a small application, verification may use a local runtime and real test database. Distributed systems need isolated routing or per-change environments and cross-service scenarios. Embedded, mobile, data, and infrastructure projects require their own execution targets. The orchestration contract can be reused across those projects; their sensors cannot be assumed interchangeable.

Inspired by [Building an agentic software factory? Start with the sensor](https://thenewstack.io/agentic-software-factory-sensor/).
