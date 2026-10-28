"""Exercise the persistence sensor and its rejection of misleading documentation."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from test_httpstats_integration import INTEGRATION, adapter
from test_httpstats_utf8 import utf8_reference
sys.path.insert(0, str(INTEGRATION))
from history_checks import verify, verify_documentation
sys.path.pop(0)

REFERENCE = Path(__file__).parent / 'fixtures/history_reference.py'


def documentation():
    saved = {'id': 1, 'text': 'hé hé', 'analysis': {'characters': 5, 'words': 2, 'lines': 1, 'utf8_bytes': 7}}
    examples = [{'method': 'POST', 'path': '/analyses', 'json': {'text': 'hé hé', 'include_utf8_bytes': True}, 'status': 201, 'response': saved},
                {'method': 'GET', 'path': '/analyses/1', 'status': 200, 'response': saved}]
    return 'Run with --database; curl examples follow.\n```json history-examples\n' + json.dumps(examples, ensure_ascii=False) + '\n```\n'


class HistorySensorTests(unittest.TestCase):
    def test_reference_passes_full_contract(self):
        cases = verify(REFERENCE)
        self.assertEqual(len(cases), 119)
        self.assertEqual(sum(c['baseline'] for c in cases), 89)
        self.assertTrue(all(c['passed'] for c in cases), [c for c in cases if not c['passed']])

    def test_previous_service_is_rejected_without_losing_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'server.py'
            script.write_text(utf8_reference())
            cases = verify(script)
            self.assertTrue(all(c['passed'] for c in cases if c['baseline']))
            self.assertTrue(any(not c['passed'] for c in cases))

    def test_nonpersistent_storage_and_shared_database_are_rejected(self):
        for before, after in [('db.commit()', 'db.rollback()'), ("args = parser.parse_args()", "args = parser.parse_args()\n    args.database = 'shared.sqlite3'")]:
            with self.subTest(mutation=after), tempfile.TemporaryDirectory() as directory:
                script = Path(directory) / 'server.py'
                script.write_text(REFERENCE.read_text().replace(before, after))
                self.assertTrue(any(not c['passed'] for c in verify(script)))

    def test_readme_examples_execute_and_wrong_results_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            readme = Path(directory) / 'README.md'
            readme.write_text(documentation())
            self.assertTrue(all(c['passed'] for c in verify_documentation(REFERENCE, readme)))
            readme.write_text(documentation().replace('"utf8_bytes": 7', '"utf8_bytes": 6'))
            self.assertTrue(any(not c['passed'] for c in verify_documentation(REFERENCE, readme)))
            readme.write_text('Claims examples are correct but provides no executable examples.')
            self.assertFalse(verify_documentation(REFERENCE, readme)[0]['passed'])

    def test_history_adapter_checks_candidate_and_installed_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); workspace = root / 'workspace'; workspace.mkdir()
            (workspace/'server.py').write_bytes(REFERENCE.read_bytes())
            (workspace/'README.md').write_text(documentation())
            context = {'run_id': 'test', 'workspace': str(workspace), 'history': []}
            for stage in ('verify', 'security', 'release', 'deploy', 'observe'):
                output = root/stage; output.mkdir()
                result = adapter.execute({**context, 'stage': stage, 'output': str(output)}, history=True)
                self.assertEqual(result['status'], 'passed', result)
                context['history'].append({'stage': stage, 'status': result['status'], 'artifact_directory': str(output)})
