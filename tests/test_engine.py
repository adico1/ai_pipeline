import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ai_pipeline.cli import demo_config
from ai_pipeline.engine import Factory, FactoryError, STAGES, digest_tree, write_json


class FactoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.factory = Factory(self.root / "runs")
        self.config = demo_config(self.root / "config.json")

    def create(self):
        return self.factory.create(self.config, "Fix addition", demo=True)["id"]

    def approve(self, run):
        self.factory.approve(run, "test-operator", "Reviewed simulated evidence")
        return self.factory.advance(run)

    def release_gate(self, run):
        state = self.factory.advance(run)
        self.assertEqual(STAGES[state["stage"]], "design")
        state = self.approve(run)
        self.assertEqual(STAGES[state["stage"]], "release")
        return state

    def test_full_lifecycle_repairs_and_separate_gates(self):
        run = self.create()
        state = self.release_gate(run)
        self.assertEqual(state["repairs"], 1)
        self.assertFalse(any(a["stage"] == "release" for a in state["attempts"]))
        state = self.approve(run)
        self.assertEqual(STAGES[state["stage"]], "deploy")
        state = self.approve(run)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(len(state["attempts"]), len(STAGES) + 2)
        self.assertIsNone(self.factory.metrics()["escape_rate"])

    def test_source_change_invalidates_approval_and_reverifies(self):
        run = self.create()
        self.release_gate(run)
        self.factory.approve(run, "operator", "Reviewed")
        workspace = self.factory.directory(run) / "workspace"
        (workspace / "README.txt").write_text("new content")
        state = self.factory.advance(run)
        self.assertEqual(state["status"], "awaiting_approval")
        self.assertEqual(STAGES[state["stage"]], "release")
        self.assertEqual(sum(a["stage"] == "verify" for a in state["attempts"]), 3)
        self.assertFalse(any(a["stage"] == "release" for a in state["attempts"]))

    def test_artifact_edit_prevents_approval(self):
        run = self.create()
        state = self.release_gate(run)
        artifact = Path(state["attempts"][-1]["artifact_directory"]) / "result.json"
        artifact.write_text("{}")
        with self.assertRaisesRegex(FactoryError, "changed since review"):
            self.factory.approve(run, "operator", "Reviewed")

    def test_no_delivery_replay_after_source_changes(self):
        run = self.create()
        self.release_gate(run)
        self.approve(run)
        (self.factory.directory(run) / "workspace" / "extra.txt").write_text("changed")
        state = self.factory.advance(run)
        self.assertEqual(state["status"], "failed")
        with self.assertRaisesRegex(FactoryError, "never replayed"):
            self.factory.retry(run)

    def test_config_edit_rejected(self):
        run = self.create()
        path = self.factory.directory(run) / "config.json"
        path.write_text(path.read_text() + "\n")
        with self.assertRaisesRegex(FactoryError, "configuration or task changed"):
            self.factory.advance(run)

    def test_missing_result_is_failure(self):
        config = json.loads(self.config.read_text())
        config["stages"]["requirements"]["command"] = [sys.executable, "-c", "print('not evidence')"]
        write_json(self.config, config)
        state = self.factory.advance(self.create())
        self.assertEqual(state["status"], "failed")
        self.assertIn("result.json", state["attempts"][-1]["error"])

    def test_timeout_records_failure(self):
        config = json.loads(self.config.read_text())
        config["stages"]["requirements"] = {"command": [sys.executable, "-c", "import time; time.sleep(10)"], "timeout_seconds": 0.05}
        write_json(self.config, config)
        state = self.factory.advance(self.create())
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["attempts"][-1]["error"], "Adapter timed out")

    def test_repair_budget_exhaustion(self):
        config = json.loads(self.config.read_text())
        config["max_repairs"] = 0
        write_json(self.config, config)
        run = self.create()
        self.factory.advance(run)
        state = self.approve(run)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(STAGES[state["stage"]], "verify")

    def test_readonly_adapter_cannot_silently_change_source(self):
        config = json.loads(self.config.read_text())
        config["max_repairs"] = 0
        config["stages"]["verify"]["command"] = [sys.executable, "-c",
            "import os,json; from pathlib import Path; Path('calculator.py').write_text('modified'); Path(os.environ['FACTORY_OUTPUT'],'result.json').write_text(json.dumps({'status':'passed','summary':'ok'}))"]
        write_json(self.config, config)
        run = self.create()
        self.factory.advance(run)
        state = self.approve(run)
        self.assertEqual(state["status"], "failed")
        self.assertIn("modified source", state["attempts"][-1]["error"])

    def test_git_worktree_isolates_original(self):
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "app.txt").write_text("original")
        subprocess.run(["git", "-C", str(repo), "add", "app.txt"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "Initial"], check=True)
        config = json.loads(self.config.read_text())
        config.pop("demo")
        config["repository"] = str(repo)
        write_json(self.config, config)
        state = self.factory.create(self.config, "Task")
        (self.factory.directory(state["id"]) / "workspace" / "app.txt").write_text("changed")
        self.assertEqual((repo / "app.txt").read_text(), "original")
        self.assertIsNotNone(state["base_commit"])

    def test_lock_and_interruption(self):
        run = self.create()
        directory = self.factory.directory(run)
        with self.factory.lock(directory):
            with self.assertRaisesRegex(FactoryError, "already"):
                self.factory.advance(run)
        state = self.factory.status(run)
        state["status"] = "running"
        self.factory.save(directory, state)
        with self.assertRaisesRegex(FactoryError, "Interrupted"):
            self.factory.advance(run)
        self.factory.retry(run)
        self.assertEqual(self.factory.advance(run)["status"], "awaiting_approval")

    def test_retry_preserves_interrupted_artifacts(self):
        run = self.create()
        directory = self.factory.directory(run)
        orphan = directory / "artifacts" / "001-requirements-interrupted"
        orphan.mkdir(parents=True)
        (orphan / "stdout.log").write_text("Partial output")
        state = self.factory.status(run)
        state["status"] = "running"
        self.factory.save(directory, state)
        self.factory.retry(run)
        state = self.factory.advance(run)
        self.assertEqual(state["status"], "awaiting_approval")
        self.assertEqual((orphan / "stdout.log").read_text(), "Partial output")

    def test_command_wrapper_captures_real_exit_status(self):
        wrapper = Path(__file__).resolve().parents[1] / "ai_pipeline" / "command_adapter.py"
        for exit_code in (0, 7):
            with self.subTest(exit_code=exit_code):
                config = json.loads(self.config.read_text())
                config["stages"]["requirements"]["command"] = [sys.executable, str(wrapper),
                    "--summary", "Command executed", "--", sys.executable, "-c", f"raise SystemExit({exit_code})"]
                write_json(self.config, config)
                state = self.factory.advance(self.create())
                self.assertEqual(state["status"], "awaiting_approval" if exit_code == 0 else "failed")
                self.assertEqual(state["attempts"][0]["result"]["exit_code"], exit_code)


if __name__ == "__main__":
    unittest.main()
