# Targeted documentation repair control

This evaluator copies the saved six-example Taskboard candidate and verifies
that the only failing acceptance case is the README rename-example sequence.
It runs the production CrewAI implementation writer once, with the normal
no-progress and handoff safeguards. The task explicitly limits changes to that
README block. No reviewer or other lifecycle stage executes.

After the writer returns (or fails), independent checks run again. Success requires
passing checks, changes only to README.md, exact preservation of text outside the
rename block, and unchanged original candidate and factory inputs. The evaluator
never retries the writer or repairs its output. A postflight check after a failure
is read-only measurement, not continuation of the writer.

```sh
uv run python evaluations/documentation_repair/run.py \
  --source-run 40bc26ebeb3a --output .factory/documentation-repair-control
```

Use `--preflight-only` with a separate new output directory to validate the fixture
without contacting the model. Inspect `results.json` and the candidate-check
artifacts. One guided success does not establish autonomous lifecycle reliability.
