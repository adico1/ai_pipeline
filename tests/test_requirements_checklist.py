import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_pipeline.cli import demo_config
from ai_pipeline.engine import Factory, FactoryError, load_config, write_json
from ai_pipeline.requirements_checklist import assemble_requirements, assembly_guardrail, document_errors, validate_checklist
from ai_pipeline.crewai_adapter import build_crew, SDLCStageFlow
from crewai import BaseLLM
from pydantic import ValidationError
from types import SimpleNamespace


RULES = [
    {"id": "exit", "requirement": "Invalid inputs exit 2.", "task_quote": "Invalid inputs exit 2."},
    {"id": "default", "requirement": "Default database is tasks.sqlite3.", "task_quote": "Default database is tasks.sqlite3."},
]
TASK = " ".join(row['task_quote'] for row in RULES)
DOCUMENT = {
    "objective": "Specify behavior", "scope": ["CLI"], "constraints": ["Preserve the interface"],
    "acceptance_criteria": [row['requirement'] for row in RULES], "open_questions": [],
    "checklist": [{"id": row['id'], "acceptance_criterion_index": index} for index, row in enumerate(RULES)],
}
ANALYSIS = {key: DOCUMENT[key] for key in ('objective', 'scope', 'constraints', 'open_questions')}


class ChecklistLLM(BaseLLM):
    """Exercise assembled writer output and independent review offline."""
    def __init__(self, blocked=False):
        super().__init__(model="checklist-test", temperature=0)
        self.calls = 0
        self.messages = []
        self.blocked = blocked

    def supports_function_calling(self):
        return False

    def call(self, messages, **kwargs):
        self.calls += 1
        self.messages.append(copy.deepcopy(messages))
        if self.calls % 2:
            value = copy.deepcopy(ANALYSIS)
        else:
            value = {"status": "blocked" if self.blocked else "passed", "summary": "Independent review verdict", "findings": [], "next_actions": []}
        return 'Final Answer: ' + json.dumps(value)


class RequirementsChecklistTests(unittest.TestCase):
    def test_exact_rule_mapping_passes_and_changed_values_fail(self):
        self.assertEqual(document_errors(DOCUMENT, RULES), [])
        for replacement in ('Invalid inputs exit 1.', 'Invalid inputs return an error.'):
            document = copy.deepcopy(DOCUMENT)
            document['acceptance_criteria'][0] = replacement
            self.assertTrue(document_errors(document, RULES))

    def test_mapping_omissions_duplicates_unknown_ids_and_wrong_indices_fail(self):
        for mapping in (
            [], [DOCUMENT['checklist'][0]], [DOCUMENT['checklist'][0]] * 2,
            [{'id': 'unknown', 'acceptance_criterion_index': 0}, DOCUMENT['checklist'][1]],
            [{'id': 'exit', 'acceptance_criterion_index': 99}, DOCUMENT['checklist'][1]],
            [{'id': 'exit', 'acceptance_criterion_index': True}, DOCUMENT['checklist'][1]],
            [{'id': 'exit', 'acceptance_criterion_index': 1}, DOCUMENT['checklist'][1]],
        ):
            with self.subTest(mapping=mapping):
                self.assertTrue(document_errors({**DOCUMENT, 'checklist': mapping}, RULES))

    def test_checklist_source_and_configuration_validation(self):
        validate_checklist(RULES, TASK)
        for rules in ([], RULES + [RULES[0]], [{**RULES[0], 'requirement': ''}]):
            with self.assertRaises(ValueError):
                validate_checklist(rules)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = demo_config(root / 'config.json')
            config = json.loads(path.read_text())
            config['stages']['requirements'] = {'backend': 'crewai', 'crewai': {'requirements_checklist': RULES}}
            write_json(path, config)
            load_config(path)
            factory = Factory(root / 'runs')
            with self.assertRaisesRegex(FactoryError, 'absent from the original task'):
                factory.create(path, 'Different task', demo=True)
            self.assertEqual(list((root / 'runs').iterdir()), [])
            config['stages']['design'] = config['stages']['requirements']
            write_json(path, config)
            with self.assertRaisesRegex(FactoryError, 'only supported'):
                load_config(path)

    def test_assembly_preserves_rules_and_rejects_writer_overrides_or_missing_fields(self):
        self.assertEqual(assemble_requirements(ANALYSIS, RULES).model_dump(), DOCUMENT)
        for analysis in ({**ANALYSIS, 'acceptance_criteria': ['Exit 1']},
                         {**ANALYSIS, 'checklist': []}, {**ANALYSIS, 'objective': ''}, {}):
            with self.subTest(analysis=analysis), self.assertRaises(ValidationError):
                assemble_requirements(analysis, RULES)

    def test_unparsed_writer_output_fails_closed_and_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guardrail = assembly_guardrail(RULES, root)
            passed, error = guardrail(SimpleNamespace(pydantic=None, raw='not a document'))
            self.assertFalse(passed)
            self.assertIn('INVALID', error)
            log = json.loads((root / 'requirements-checklist-validation.json').read_text())
            self.assertEqual(log['attempts'][0]['writer_raw'], 'not a document')

    def test_real_crew_reviewer_receives_canonical_document_and_preserves_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = ChecklistLLM()
            context = {'stage': 'requirements', 'task': TASK, 'workspace': str(root),
                       'output': str(root), 'history': [], 'crewai': {'requirements_checklist': RULES}}
            with patch.dict(os.environ, {'CREWAI_STORAGE_DIR': str(root / 'storage')}), patch(
                'ai_pipeline.crewai_adapter.build_crew', side_effect=lambda ctx: build_crew(ctx, llm=model)
            ):
                result = SDLCStageFlow(tracing=False).kickoff(inputs={'context': context})
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(model.calls, 2)
            self.assertEqual(result['deliverable']['checklist'], DOCUMENT['checklist'])
            self.assertEqual(result['deliverable']['acceptance_criteria'], DOCUMENT['acceptance_criteria'])
            reviewer_input = str(model.messages[1])
            for rule in RULES:
                self.assertIn(rule['requirement'], reviewer_input)
            self.assertIn('acceptance_criterion_index', reviewer_input)
            self.assertEqual(json.loads((root / 'requirements-analysis.json').read_text()), ANALYSIS)
            attempts = json.loads((root / 'requirements-checklist-validation.json').read_text())['attempts']
            self.assertEqual([item['passed'] for item in attempts], [True])

    def test_assembled_criteria_do_not_bypass_independent_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = ChecklistLLM(blocked=True)
            context = {'stage': 'requirements', 'task': TASK, 'workspace': str(root),
                       'output': str(root), 'history': [], 'crewai': {'requirements_checklist': RULES}}
            with patch.dict(os.environ, {'CREWAI_STORAGE_DIR': str(root / 'storage')}), patch(
                'ai_pipeline.crewai_adapter.build_crew', side_effect=lambda ctx: build_crew(ctx, llm=model)
            ):
                result = SDLCStageFlow(tracing=False).kickoff(inputs={'context': context})
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['review_revisions'], 2)
            self.assertEqual(model.calls, 6)

    def test_all_taskboard_rules_detect_individual_omission_or_value_change(self):
        root = Path(__file__).resolve().parents[1]
        config = load_config(root / 'projects/taskboard-rename-checklisted.json')
        rules = config['stages']['requirements']['crewai']['requirements_checklist']
        validate_checklist(rules, (root / 'projects/taskboard-rename-task.txt').read_text())
        document = {**DOCUMENT, 'acceptance_criteria': [r['requirement'] for r in rules],
                    'checklist': [{'id': r['id'], 'acceptance_criterion_index': i} for i, r in enumerate(rules)]}
        self.assertEqual(document_errors(document, rules), [])
        for index in range(len(rules)):
            with self.subTest(requirement=rules[index]['id']):
                missing = copy.deepcopy(document)
                missing['checklist'].pop(index)
                self.assertTrue(document_errors(missing, rules))
                changed = copy.deepcopy(document)
                changed['acceptance_criteria'][index] = 'Preserve behavior.'
                self.assertTrue(document_errors(changed, rules))
