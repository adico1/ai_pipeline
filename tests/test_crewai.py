import json
import os
from pathlib import Path
import tempfile
import sys
import subprocess
import unittest
from unittest.mock import patch

os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"
os.environ["CREWAI_TRACING_ENABLED"] = "false"

from crewai import BaseLLM
from ai_pipeline.crewai_adapter import CandidateProgress, CandidateStalled, ImplementationIncomplete, implementation_guardrail, concise_report, SDLCStageFlow, build_crew, run_candidate_checks, safe_path, stage_inputs, workspace_tools
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
            "summary": "Local integration-test deliverable", "findings": ["Acceptance criteria recorded"], "next_actions": [],
            "objective": "Correct addition", "scope": ["Integer inputs"],
            "acceptance_criteria": ["2 + 3 returns 5"], "constraints": ["Preserve API"], "open_questions": [],
            "approach": "Use integer addition", "interfaces": ["Preserve add(a, b)"],
            "data_flow": ["Inputs to addition to return value"], "decisions_and_tradeoffs": ["Use the built-in operator, no dependencies"],
            "edge_cases": ["Negative and zero inputs"], "verification_strategy": ["Run independent addition cases"],
            "ordered_steps": [{"action": "Replace subtraction with addition", "target": "calculator.py", "done_when": "Function uses the addition operator"}],
            "verification_steps": ["Run independent addition cases"], "risks_and_mitigations": ["Preserve the existing signature"]})

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
        self.assertEqual(json.loads((self.output / "requirements.json").read_text())["acceptance_criteria"], ["2 + 3 returns 5"])

    def test_requirements_retry_does_not_reuse_failed_implementation_judgment(self):
        failed = {"stage": "requirements", "status": "failed", "result": {"summary": "BUG MUST BE FIXED ALREADY"}}
        data = stage_inputs({**self.context, "history": [failed], "previous_attempt": failed})
        self.assertEqual(data["completed_upstream_stages"], [])
        self.assertIsNone(data["repair_feedback"])
        crew = build_crew(self.context, llm=LocalTestLLM())
        self.assertEqual(crew.agents[1].tools, [])

    def test_implementation_receives_upstream_requirements_and_real_test_failure(self):
        requirements = {"stage": "requirements", "status": "passed", "result": {"deliverable": "Document"}}
        failure = {"stage": "verify", "status": "failed", "result": {"summary": "empty input failed"}}
        data = stage_inputs({**self.context, "stage": "implement", "history": [requirements, failure], "previous_attempt": failure})
        self.assertEqual(data["completed_upstream_stages"], [requirements])
        self.assertEqual(data["repair_feedback"], failure)

    def test_blocked_review_fails_stage(self):
        with patch("ai_pipeline.crewai_adapter.build_crew", side_effect=lambda context: build_crew(context, llm=LocalTestLLM(blocked=True))):
            result = SDLCStageFlow().kickoff(inputs={"context": self.context})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["review_revisions"], 2)
        self.assertEqual(len(list(self.output.glob('review-round-*.json'))), 3)

    def test_rejected_document_is_revised_with_feedback_before_passing(self):
        contexts = []
        def make_crew(context):
            contexts.append(dict(context))
            return build_crew(context, llm=LocalTestLLM(blocked=not bool(context.get("stage_revision_feedback"))))
        with patch("ai_pipeline.crewai_adapter.build_crew", side_effect=make_crew):
            result = SDLCStageFlow(tracing=False).kickoff(inputs={"context": {**self.context, "stage": "design"}})
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["review_revisions"], 1)
        self.assertEqual(contexts[1]["stage_revision_feedback"]["review"]["status"], "blocked")
        self.assertEqual(json.loads((self.output / "review-round-0.json").read_text())["review"]["status"], "blocked")

    def test_design_and_plan_documents_survive_stage_handoff(self):
        for stage, field in (("design", "decisions_and_tradeoffs"), ("plan", "ordered_steps")):
            with self.subTest(stage=stage), patch("ai_pipeline.crewai_adapter.build_crew", side_effect=lambda context: build_crew(context, llm=LocalTestLLM())):
                result = SDLCStageFlow(tracing=False).kickoff(inputs={"context": {**self.context, "stage": stage}})
                self.assertEqual(result["status"], "passed")
                document = json.loads((self.output / f"{stage}.json").read_text())
                self.assertTrue(document[field])
                self.assertEqual(result["deliverable"], document)
                upstream = {"stage": stage, "status": "passed", "result": result}
                downstream = stage_inputs({**self.context, "stage": "implement", "history": [upstream]})
                self.assertEqual(downstream["completed_upstream_stages"][0]["result"]["deliverable"], document)

    def test_bug_report_does_not_satisfy_design_or_plan_schema(self):
        from pydantic import ValidationError
        from ai_pipeline.stage_contracts import DesignDocument, PlanDocument
        for schema in (DesignDocument, PlanDocument):
            with self.subTest(schema=schema.__name__), self.assertRaises(ValidationError):
                schema.model_validate({"summary": "Current implementation is broken", "next_actions": ["Fix code"]})

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

    def test_candidate_check_tool_observes_current_files_not_previous_failures(self):
        checker = self.root / "checker.py"
        checker.write_text("import os,json\nfrom pathlib import Path\nok = Path('candidate.txt').read_text() == 'fixed'\nPath(os.environ['FACTORY_OUTPUT'],'result.json').write_text(json.dumps({'status':'passed' if ok else 'failed','summary':'current file checked'}))\nraise SystemExit(0 if ok else 1)\n")
        context = {**self.context, "checks": {name: {"command": [sys.executable, str(checker)]} for name in ("verify", "security")}}
        candidate = self.workspace / "candidate.txt"
        candidate.write_text("broken")
        first = json.loads(run_candidate_checks(context))
        self.assertTrue(all(check["status"] == "failed" for check in first["checks"]))
        candidate.write_text("fixed")
        second = json.loads(run_candidate_checks(context))
        self.assertTrue(all(check["status"] == "passed" for check in second["checks"]))
        self.assertEqual(len(list((self.output / "candidate-checks").iterdir())), 4)

    def test_candidate_check_missing_results_fail_closed(self):
        context = {**self.context, "checks": {name: {"command": [sys.executable, "-c", "pass"]} for name in ("verify", "security")}}
        self.assertTrue(all(check["status"] == "failed" for check in json.loads(run_candidate_checks(context))["checks"]))

    def implementation_context(self):
        checker = self.root / "check.py"
        checker.write_text("import json,os\nfrom pathlib import Path\nok=Path('candidate.txt').read_text()=='fixed'\nPath(os.environ['FACTORY_OUTPUT'],'result.json').write_text(json.dumps({'status':'passed' if ok else 'failed','summary':'candidate must be fixed'}))\nraise SystemExit(0 if ok else 1)\n")
        (self.workspace / "candidate.txt").write_text("broken")
        return {**self.context, "stage": "implement", "checks": {name: {"command": [sys.executable, str(checker)]} for name in ("verify", "security")}}

    def test_handoff_rechecks_stale_passing_evidence(self):
        from types import SimpleNamespace
        context = self.implementation_context()
        source = self.workspace / "candidate.txt"
        source.write_text("fixed")
        run_candidate_checks(context)
        guard = implementation_guardrail(context)
        self.assertTrue(guard(SimpleNamespace(raw="done"))[0])
        source.write_text("broken again")
        self.assertFalse(guard(SimpleNamespace(raw="done"))[0])
        with self.assertRaises(ImplementationIncomplete):
            guard(SimpleNamespace(raw="assessment only"))

    def test_real_writer_corrects_assessment_before_review(self):
        context = self.implementation_context()
        class WriterLLM(LocalTestLLM):
            def call(self, *args, **kwargs):
                responses = [
                    'Final Answer: The implementation is missing; implement it next.',
                    'Thought: Implement now.\nAction: write_source_file\nAction Input: {"path":"candidate.txt","content":"fixed"}',
                    'Thought: Verify.\nAction: check_current_candidate\nAction Input: {}',
                    'Final Answer: Implemented candidate.txt and checks pass.',
                    'Thought: Review independently.\nAction: check_current_candidate\nAction Input: {}',
                    'Final Answer: {"status":"passed","summary":"Independent checks passed","findings":[],"next_actions":[]}',
                ]
                result = responses[min(self.calls, len(responses)-1)]
                if self.calls >= 5:
                    result = 'Final Answer: ' + json.dumps({"status": "passed", "evidence_ids": [], "source_concerns": [],
                        "commentary": "Independent checks passed"})
                self.calls += 1
                return result
        model = WriterLLM()
        with patch("ai_pipeline.crewai_adapter.build_crew", side_effect=lambda ctx: build_crew(ctx, llm=model)):
            result = SDLCStageFlow(tracing=False).kickoff(inputs={"context": context})
        self.assertEqual(result["status"], "passed")
        self.assertEqual((self.workspace / "candidate.txt").read_text(), "fixed")
        records = [json.loads(line) for line in (self.output / "implementation-handoff.jsonl").read_text().splitlines()]
        self.assertEqual([record["passed"] for record in records], [False, True])

    def test_assessment_only_writer_stops_after_one_correction(self):
        context = self.implementation_context()
        model = LocalTestLLM()
        with patch("ai_pipeline.crewai_adapter.build_crew", side_effect=lambda ctx: build_crew(ctx, llm=model)):
            result = SDLCStageFlow(tracing=False).kickoff(inputs={"context": context})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["stop_reason"], "implementation_incomplete")
        self.assertEqual(model.calls, 2)

    def test_feedback_groups_modes_and_retains_distinct_failures(self):
        failures = [{"case": "delimiter", "delimiter": delimiter, "mode": mode,
                     "expected_exit": 2, "exit_code": 0, "stdout": "x" * 3000}
                    for delimiter in ("Z", "0", "é") for mode in ("stdin", "before", "after")]
        report = concise_report({"status": "failed", "failed_cases": failures})
        self.assertEqual(report["failed_case_count"], 9)
        self.assertEqual(report["failure_group_count"], 3)
        self.assertTrue(all(g["occurrences"] == 3 for g in report["failure_groups"]))
        self.assertLess(len(json.dumps(report)), 2500)
        self.assertEqual(len(failures[0]["stdout"]), 3000)

    def test_unchanged_failure_reuses_checks_then_stops(self):
        checker = self.root / "checker.py"
        checker.write_text("import os,json\nfrom pathlib import Path\nPath(os.environ['FACTORY_OUTPUT'],'result.json').write_text(json.dumps({'status':'failed','summary':'still broken'}))\n")
        context = {**self.context, "checks": {name: {"command": [sys.executable, str(checker)]} for name in ("verify", "security")}}
        progress = CandidateProgress()
        run_candidate_checks(context, progress)
        cached = json.loads(run_candidate_checks(context, progress))
        self.assertIn("Source unchanged", cached["progress"])
        with self.assertRaises(CandidateStalled):
            run_candidate_checks(context, progress)
        self.assertEqual(len(list((self.output / "candidate-checks").iterdir())), 2)

    def test_changed_source_same_failures_stops_but_improvement_resets(self):
        progress = CandidateProgress()
        payload = {"checks": [{"status": "failed"}]}
        for source in ("a", "b"):
            progress.after(source, dict(payload), {"error": "same"})
        with self.assertRaises(CandidateStalled):
            progress.after("c", dict(payload), {"error": "same"})
        progress.after("d", dict(payload), {"error": "different"})
        self.assertEqual(progress.repeats, 1)
        progress.after("e", {"checks": [{"status": "passed"}]}, {})
        self.assertIsNone(progress.before("e"))

    def test_stagnation_flow_fails_closed_without_reviewer_or_revision(self):
        class StalledCrew:
            def kickoff(self):
                raise CandidateStalled("No progress")
        with patch("ai_pipeline.crewai_adapter.build_crew", return_value=StalledCrew()) as build:
            result = SDLCStageFlow(tracing=False).kickoff(inputs={"context": {**self.context, "stage": "implement"}})
        self.assertEqual(build.call_count, 1)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["stop_reason"], "no_progress")
        self.assertTrue((self.output / "no-progress.json").exists())

    def test_real_crewai_tool_loop_is_interrupted_on_no_progress(self):
        class RepeatingLLM(LocalTestLLM):
            def call(self, *args, **kwargs):
                self.calls += 1
                action = "check_current_candidate" if self.calls % 2 else "list_source_files"
                return f'Thought: Inspect current candidate.\nAction: {action}\nAction Input: {{}}'
        model = RepeatingLLM()
        with patch("ai_pipeline.crewai_adapter.build_crew", side_effect=lambda context: build_crew(context, llm=model)):
            result = SDLCStageFlow(tracing=False).kickoff(inputs={"context": {**self.context, "stage": "implement"}})
        self.assertEqual(result["stop_reason"], "no_progress")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(model.calls, 5)

    def test_candidate_check_tool_has_no_model_command_parameters(self):
        crew = build_crew({**self.context, "stage": "implement"}, llm=LocalTestLLM())
        for agent in crew.agents:
            tool = next(tool for tool in agent.tools if tool.name == "check_current_candidate")
            self.assertEqual(tool.args_schema.model_fields, {})

    def test_reviewer_does_not_receive_historical_failure_verdict(self):
        failed = {"stage": "implement", "status": "failed", "result": {"summary": "HISTORICAL_POLICY_FAILURE"}}
        crew = build_crew({**self.context, "stage": "implement", "previous_attempt": failed}, llm=LocalTestLLM())
        self.assertIn("HISTORICAL_POLICY_FAILURE", crew.tasks[0].description)
        self.assertNotIn("HISTORICAL_POLICY_FAILURE", crew.tasks[1].description)

    def test_review_context_contains_actual_repaired_source(self):
        subprocess.run(["git", "init", "-q", str(self.workspace)], check=True)
        source = self.workspace / "app.py"
        source.write_text('words = text.split(" ")\n')
        subprocess.run(["git", "-C", str(self.workspace), "add", "app.py"], check=True)
        subprocess.run(["git", "-C", str(self.workspace), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "baseline"], check=True)
        base = subprocess.check_output(["git", "-C", str(self.workspace), "rev-parse", "HEAD"], text=True).strip()
        source.write_text('words = text.split()\n')
        context = {**self.context, "stage": "review", "base_commit": base}
        snapshot = stage_inputs(context)["current_changed_source"]
        self.assertEqual(snapshot, [{"path": "app.py", "current_text": 'words = text.split()\n'}])

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
