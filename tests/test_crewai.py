import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"
os.environ["CREWAI_TRACING_ENABLED"] = "false"

from crewai import BaseLLM
from ai_pipeline.crewai_adapter import SDLCStageFlow, build_crew, safe_path, workspace_tools
from ai_pipeline.cli import demo_config
from ai_pipeline.engine import Factory, FactoryError, load_config, write_json


class LocalTestLLM(BaseLLM):
    """Scripted, network-free model; the actual CrewAI agents/crew/flow execute."""
    def __init__(self, blocked=False):
        super().__init__(model="local-test", temperature=0)
        self.blocked = blocked
        self.calls = 0

    def call(self, messages, tools=None, callbacks=None, available_functions=None, **kwargs):
        self.calls += 1
        return 'Final Answer: ' + json.dumps({"status": "blocked" if self.blocked else "passed",
            "summary": "Local integration-test deliverable", "findings": ["Acceptance criteria recorded"], "next_actions": []})

    def supports_function_calling(self):
        return False


class CrewAITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.output = self.root / "output"
        self.output.mkdir()
        self.context = {"stage": "requirements", "task": "Describe addition acceptance criteria",
                        "workspace": str(self.workspace), "output": str(self.output), "history": []}
        self.env = patch.dict(os.environ, {"CREWAI_STORAGE_DIR": str(self.root / "storage")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_real_crew_and_flow_with_local_model(self):
        model = LocalTestLLM()
        with patch("ai_pipeline.crewai_adapter.build_crew", side_effect=lambda context: build_crew(context, llm=model)):
            result = SDLCStageFlow().kickoff(inputs={"context": self.context})
        self.assertEqual(result["status"], "passed")
        self.assertGreaterEqual(model.calls, 2)
        self.assertEqual(json.loads((self.output / "result.json").read_text())["framework"], "crewai")
        self.assertTrue((self.output / "crew-report.md").exists())

    def test_blocked_review_fails_stage(self):
        with patch("ai_pipeline.crewai_adapter.build_crew", side_effect=lambda context: build_crew(context, llm=LocalTestLLM(blocked=True))):
            result = SDLCStageFlow().kickoff(inputs={"context": self.context})
        self.assertEqual(result["status"], "failed")

    def test_only_implementation_can_write(self):
        for stage in ("requirements", "implement", "review"):
            crew = build_crew({**self.context, "stage": stage}, llm=LocalTestLLM())
            names = [t.name for t in crew.agents[0].tools]
            self.assertEqual("write_source_file" in names, stage == "implement")
            self.assertNotIn("write_source_file", [t.name for t in crew.agents[1].tools])

    def test_stage_and_reviewer_model_selection(self):
        with patch.dict(os.environ, {"FACTORY_MODEL": "default-model",
                                     "FACTORY_MODEL_REQUIREMENTS": "stage-model",
                                     "FACTORY_REVIEW_MODEL": "review-model"}), \
             patch("ai_pipeline.crewai_adapter.LLM", side_effect=lambda **kwargs: LocalTestLLM()) as model:
            build_crew(self.context)
            self.assertEqual([call.kwargs["model"] for call in model.call_args_list],
                             ["stage-model", "review-model"])
            model.reset_mock()
            build_crew({**self.context, "crewai": {"model": "config-model", "review_model": "config-review"}})
            self.assertEqual([call.kwargs["model"] for call in model.call_args_list],
                             ["config-model", "config-review"])

    def test_tools_write_and_read_candidate(self):
        tools = {t.name: t for t in workspace_tools(self.workspace, writable=True)}
        tools["write_source_file"].run(path="src/app.py", content="answer = 42\n")
        self.assertEqual(tools["read_source_file"].run(path="src/app.py"), "answer = 42\n")
        self.assertIn("src/app.py", tools["list_source_files"].run())

    def test_paths_reject_escape_secrets_and_symlinks(self):
        (self.workspace / "linked").symlink_to(self.root)
        for path in ("../outside", "/tmp/outside", ".env", ".git/config", "linked/output/test", "credentials.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                safe_path(self.workspace, path)

    def test_verification_cannot_be_replaced_with_llm(self):
        config_path = demo_config(self.root / "project.json")
        config = json.loads(config_path.read_text())
        config["stages"]["verify"] = {"backend": "crewai"}
        write_json(config_path, config)
        with self.assertRaisesRegex(FactoryError, "independent command"):
            load_config(config_path)

    def test_engine_dispatches_crewai_and_missing_model_fails_closed(self):
        config_path = demo_config(self.root / "project.json")
        config = json.loads(config_path.read_text())
        config["stages"]["requirements"] = {"backend": "crewai", "timeout_seconds": 30}
        write_json(config_path, config)
        factory = Factory(self.root / "runs")
        run = factory.create(config_path, "Test missing model", demo=True)
        with patch.dict(os.environ, {"FACTORY_MODEL": ""}):
            result = factory.advance(run["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("FACTORY_MODEL", result["attempts"][0]["result"]["summary"])


if __name__ == "__main__":
    unittest.main()
