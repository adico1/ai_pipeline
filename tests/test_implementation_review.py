import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from crewai import BaseLLM
from ai_pipeline.crewai_adapter import build_crew, run_candidate_checks, safe_path
from ai_pipeline.engine import digest_tree
from ai_pipeline.implementation_review import ImplementationReview, ReviewerEvidence


class ImplementationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.source = self.workspace / 'app.py'
        self.source.write_text('value = "correct"\n')
        checker = self.root / 'check.py'
        checker.write_text("import os,json\nfrom pathlib import Path\nok='correct' in Path('app.py').read_text()\nPath(os.environ['FACTORY_OUTPUT'],'result.json').write_text(json.dumps({'status':'passed' if ok else 'failed','summary':'correct value required'}))\nraise SystemExit(0 if ok else 1)\n")
        self.context = {'stage': 'implement', 'task': 'Set value to correct.', 'workspace': str(self.workspace),
                        'output': str(self.root), 'history': [], 'checks': {stage: {'command': [sys.executable, str(checker)]} for stage in ('verify', 'security')}}
        self.evidence = ReviewerEvidence(self.context, run_candidate_checks, safe_path)

    def report(self, **changes):
        return ImplementationReview.model_validate({
            'status': 'passed', 'summary': 'Reviewed', 'findings': [], 'next_actions': [],
            'blocking_findings': [], 'source_digest': digest_tree(self.workspace), **changes,
        })

    def blocked(self, citation):
        return self.report(status='blocked', findings=['Concrete defect'],
                           blocking_findings=[{'finding': 'Concrete defect', 'citations': [citation]}])

    def test_writer_evidence_does_not_count_as_reviewer_check(self):
        run_candidate_checks(self.context)
        self.assertTrue(self.evidence.validate(self.report())[0])
        self.evidence.check()
        self.assertEqual(self.evidence.validate(self.report())[0], [])

    def test_stale_checks_and_digests_fail(self):
        self.evidence.check()
        old = self.report()
        self.source.write_text('value = "broken"\n')
        self.assertTrue(self.evidence.validate(old)[0])
        self.assertTrue(self.evidence.validate(self.report())[0])

    def test_false_failure_citations_and_uncited_blockers_fail(self):
        self.evidence.check()
        report = self.blocked({'kind': 'check', 'check_stage': 'verify', 'quote': 'correct value required'})
        self.assertTrue(self.evidence.validate(report)[0])
        self.assertTrue(self.evidence.validate(self.report(status='blocked'))[0])
        report = self.blocked({'kind': 'source', 'path': 'app.py', 'quote': 'not present'})
        self.assertTrue(self.evidence.validate(report)[0])

    def test_current_failed_check_is_valid_and_cannot_be_passed(self):
        self.source.write_text('value = "broken"\n')
        self.evidence.check()
        evidence_id = next(key for key in self.evidence.latest['check_evidence'] if key.startswith('verify:'))
        report = self.blocked({'kind': 'check', 'check_stage': 'verify', 'evidence_id': evidence_id})
        self.assertEqual(self.evidence.validate(report)[0], [])
        self.assertTrue(self.evidence.validate(self.report())[0])

    def test_ids_are_stable_and_evidence_is_attached_without_model_quotes(self):
        self.source.write_text('value = "broken"\n')
        first = json.loads(self.evidence.check())['check_evidence']
        second = json.loads(self.evidence.check())['check_evidence']
        self.assertEqual(first, second)
        key = next(key for key in first if key.startswith('verify:'))
        report = self.blocked({'kind': 'check', 'check_stage': 'verify', 'evidence_id': key})
        report.resolved_check_evidence = {'fabricated': {'detail': 'fake'}}
        self.assertEqual(self.evidence.validate(report)[0], [])
        self.assertEqual(report.resolved_check_evidence, {key: first[key]})
        report.blocking_findings[0].inferred_cause = 'Unsafe SQL'
        self.assertTrue(self.evidence.validate(report)[0])
        report.blocking_findings[0].inferred_cause = None
        citation = report.blocking_findings[0].citations[0]
        citation.check_stage = 'security'
        self.assertTrue(self.evidence.validate(report)[0])
        citation.check_stage = 'verify'
        citation.evidence_id = 'invented'
        self.assertTrue(self.evidence.validate(report)[0])
        citation.evidence_id = key
        self.source.write_text('value = "correct"\n')
        self.evidence.check()
        report.source_digest = digest_tree(self.workspace)
        self.assertTrue(self.evidence.validate(report)[0])

    def test_source_defect_can_block_even_when_checks_pass(self):
        self.source.write_text('value = "correct"\nunsafe = True\n')
        self.evidence.check()
        report = self.blocked({'kind': 'source', 'path': 'app.py', 'quote': 'unsafe = True'})
        errors, locations = self.evidence.validate(report)
        self.assertEqual(errors, [])
        self.assertEqual(locations[0]['line'], 2)
        report.findings.append('Uncited additional blocker')
        self.assertTrue(self.evidence.validate(report)[0])

    def test_path_escape_and_symlink_citations_fail(self):
        self.evidence.check()
        outside = self.root / 'outside.py'
        outside.write_text('outside = True')
        (self.workspace / 'link.py').symlink_to(outside)
        # Recheck after adding the link so this tests path validation, not staleness.
        self.evidence.check()
        for path in ('../outside.py', str(outside), 'link.py'):
            report = self.blocked({'kind': 'source', 'path': path, 'quote': 'outside = True'})
            self.assertTrue(self.evidence.validate(report)[0])

    def test_known_misinterpretations_are_replaced_by_facts_and_retained_as_unverified(self):
        examples = [
            ('rename-complete-after-rename', {'id': 1, 'title': 'trimmed', 'completed': True},
             {'id': 1, 'title': '  trimmed  ', 'completed': True}, 'Completion state is lost'),
            ('rename-failed-operations-no-write', [{'id': 1, 'title': 'trimmed'}],
             [{'id': 1, 'title': '  '}], 'Invalid IDs are accepted'),
        ]
        for case, expected, actual, claim in examples:
            with self.subTest(case=case):
                payload = {'source_digest': digest_tree(self.workspace), 'checks': [
                    {'stage': 'verify', 'status': 'failed', 'report': {'failure_groups': [
                        {'example': {'case': case, 'expected': expected, 'actual': {'exit_code': 0, 'body': actual}}}]}},
                    {'stage': 'security', 'status': 'passed', 'report': {}},
                ]}
                self.evidence.run_checks = lambda context: json.dumps(payload)
                receipt = json.loads(self.evidence.check())
                key = next(iter(receipt['check_evidence']))
                report = self.blocked({'kind': 'check', 'check_stage': 'verify', 'evidence_id': key})
                report.findings = [claim]
                report.blocking_findings[0].finding = claim
                report.summary = claim
                report.next_actions = ['Repair SQL']
                output = SimpleNamespace(pydantic=report, raw=report.model_dump_json())
                valid, output = self.evidence.guardrail(output)
                self.assertTrue(valid)
                self.assertIn('/title:', output.pydantic.findings[0])
                self.assertNotIn('/completed:', output.pydantic.findings[0])
                self.assertNotIn('/id:', output.pydantic.findings[0])
                self.assertNotIn(claim, output.pydantic.summary)
                self.assertEqual(output.pydantic.next_actions, [])
                self.assertEqual(output.pydantic.unverified_model_interpretation['findings'], [claim])
                self.assertEqual(output.pydantic.unverified_model_interpretation['next_actions'], ['Repair SQL'])
                self.assertEqual(output.pydantic.status, 'blocked')

    def test_invalid_report_is_retained(self):
        passed, _ = self.evidence.guardrail(SimpleNamespace(pydantic=None, raw='not JSON'))
        self.assertFalse(passed)
        record = json.loads((self.root / 'implementation-review-validation.jsonl').read_text())
        self.assertEqual(record['raw_report'], 'not JSON')

    def test_actual_reviewer_tool_and_guardrail_accept_good_and_block_defective_source(self):
        context, workspace = self.context, self.workspace

        class ReviewerLLM(BaseLLM):
            def __init__(self, broken):
                super().__init__(model='offline-review', temperature=0)
                self.calls, self.broken = 0, broken

            def supports_function_calling(self):
                return False

            def call(self, messages, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return 'Thought: Check current source.\nAction: check_current_candidate\nAction Input: {}'
                receipts = (Path(context['output']) / 'reviewer-checks.jsonl').read_text().splitlines()
                entries = json.loads(receipts[-1])['check_evidence']
                evidence_id = next((key for key in entries if key.startswith('verify:')), None)
                finding = {'finding': 'Value is broken', 'citations': [{'kind': 'check', 'check_stage': 'verify', 'evidence_id': evidence_id}]}
                return 'Final Answer: ' + json.dumps({'status': 'blocked' if self.broken else 'passed',
                    'summary': 'Current evidence inspected', 'findings': ['Value is broken'] if self.broken else [],
                    'next_actions': [], 'source_digest': digest_tree(workspace),
                    'blocking_findings': [finding] if self.broken else []})

        for broken in (False, True):
            with self.subTest(broken=broken), patch.dict(os.environ, {'CREWAI_STORAGE_DIR': str(self.root / 'storage')}):
                self.source.write_text('value = "broken"\n' if broken else 'value = "correct"\n')
                model = ReviewerLLM(broken)
                crew = build_crew(context, llm=model)
                result = crew.tasks[1].execute_sync(agent=crew.agents[1], context='Inspect candidate')
                self.assertEqual(result.pydantic.status, 'blocked' if broken else 'passed')
                self.assertEqual(model.calls, 2)
