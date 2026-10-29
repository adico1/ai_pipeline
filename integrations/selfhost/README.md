# First self-development trial

The committed factory orchestrates a detached candidate checkout of itself.
CrewAI may change only `ai_pipeline/cli.py`, `ai_pipeline/report.py`,
`tests/test_report.py`, and `docs/report.md`. Existing tests, engine, adapters,
models and dependency definitions are protected by the external policy check.
The operator freezes all tracked runner inputs before creating the run.

The independent checks invoke the candidate CLI from an unrelated working
directory, without provider credentials and with outbound socket connections
blocked in that process. They check recorded Markdown content, deterministic
exports, errors, overwrite refusal and evidence-directory protection. This is
trusted local execution, not an adversarial security sandbox.

Candidate advisory checks run independent acceptance cases and the new report
tests within the existing 60-second tool budget. The formal verification gate
also runs the full regression suite, with existing test files protected. Release
builds a source bundle and wheel from a temporary copy. Deployment installs that
wheel to an isolated target using existing runtime dependencies. Observation
reruns acceptance against the installed package outside the repository.

The report feature is written by CrewAI, not supplied by this setup. The operator
owns this test harness and reviews normal gates. No candidate changes are copied
back to the running factory before the trial completes.
