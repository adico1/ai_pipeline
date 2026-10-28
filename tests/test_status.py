import contextlib
import io
import json
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

from ai_pipeline.cli import main
from ai_pipeline.engine import STAGES
from ai_pipeline.status import format_status


class StatusTests(unittest.TestCase):
    def state(self, status="queued", stage="requirements", attempts=None):
        return {"id": "abc123abc123", "project": "sample", "demo": False,
                "status": status, "stage": STAGES.index(stage), "repairs": 0,
                "attempts": attempts or [], "approvals": []}

    def render(self, state):
        return format_status(state, "/tmp/custom runs", "/tmp/custom settings.env")

    def attempt(self, stage, status="passed", **result):
        return {"stage": stage, "status": status, "result": result,
                "artifact_directory": f"/tmp/evidence/{stage}"}

    def test_completed_has_no_mutating_next_command_and_retains_history(self):
        state = self.state("completed", attempts=[self.attempt("implement", "failed"), self.attempt("observe")])
        state["stage"] = len(STAGES)
        output = self.render(state)
        self.assertIn("complete (11/11)", output)
        self.assertIn("Failed attempts: 1", output)
        self.assertIn("no further action required", output)
        self.assertNotIn("advance abc123abc123", output)
        self.assertNotIn("retry abc123abc123", output)

    def test_all_approval_gates_explain_evidence_and_require_real_review(self):
        for stage, phrase in [("design", "acceptance criteria"), ("release", "verify/security"), ("deploy", "digest manifest"), ("plan", "preceding stage")]:
            with self.subTest(stage=stage):
                output = self.render(self.state("awaiting_approval", stage, [self.attempt("requirements")]))
                self.assertIn(phrase, output)
                self.assertIn("/tmp/evidence/requirements", output)
                self.assertIn("not proof that approval is appropriate", output)
                command = next(line for line in output.splitlines() if " approve " in line)
                args = shlex.split(command)
                self.assertEqual(args[args.index("--state-dir") + 1], str(Path("/tmp/custom runs").resolve()))
                self.assertEqual(args[args.index("--env-file") + 1], str(Path("/tmp/custom settings.env").resolve()))
                self.assertEqual(args[args.index("--actor") + 1], "YOUR_NAME")
                self.assertTrue(args[args.index("--note") + 1])

    def test_failed_checks_are_bounded_with_conditional_retry(self):
        attempt = self.attempt("verify", "failed", summary="Failed independent checks", failed_cases=[{"name": f"case{i}", "actual": "x" * 1000} for i in range(12)])
        output = self.render(self.state("failed", "verify", [attempt]))
        self.assertIn("Failed independent checks", output)
        self.assertIn("12 (up to 5 shown)", output)
        self.assertIn("case4", output)
        self.assertNotIn("case5", output)
        self.assertIn("fix the cause before retrying", output)
        self.assertIn(" retry abc123abc123", output)
        self.assertLess(len(output), 4000)

    def test_failed_model_review_shows_findings_and_stop_reason(self):
        attempt = self.attempt("implement", "failed", findings=["Invalid delimiters accepted"], stop_reason="no_progress")
        output = self.render(self.state("failed", "implement", [attempt]))
        self.assertIn("Invalid delimiters accepted", output)
        self.assertIn("Stop reason: no_progress", output)

    def test_delivery_failure_and_later_invalidation_never_suggest_retry(self):
        for stage in ("release", "deploy", "observe"):
            with self.subTest(stage=stage):
                output = self.render(self.state("failed", stage, [self.attempt("release")]))
                self.assertIn("reconcile delivery", output)
                self.assertNotIn(" retry abc123abc123", output)
                self.assertNotIn(" advance abc123abc123", output)

    def test_running_does_not_assume_interruption(self):
        output = self.render(self.state("running"))
        self.assertIn("confirm the process stopped", output)
        self.assertNotIn(" retry abc123abc123", output)

    def test_queued_ready_and_demo(self):
        for status in ("queued", "ready"):
            state = self.state(status)
            state["demo"] = True
            output = self.render(state)
            self.assertIn("simulated demo", output)
            self.assertIn(" advance abc123abc123", output)

    def test_cli_default_and_json_are_read_only_and_json_is_lossless(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "abc123abc123"
            directory.mkdir()
            state = self.state()
            state["extra_field"] = {"preserve": [1, 2, 3]}
            path = directory / "state.json"
            path.write_text(json.dumps(state))
            before = path.read_bytes()
            for json_mode in (False, True):
                argv = ["ai-pipeline", "--state-dir", temp, "status", "abc123abc123"] + (["--json"] if json_mode else [])
                output = io.StringIO()
                with patch("sys.argv", argv), patch("ai_pipeline.cli.load_environment"), contextlib.redirect_stdout(output):
                    main()
                if json_mode:
                    self.assertEqual(json.loads(output.getvalue()), state)
                else:
                    self.assertIn("Status: queued", output.getvalue())
                self.assertEqual(path.read_bytes(), before)
