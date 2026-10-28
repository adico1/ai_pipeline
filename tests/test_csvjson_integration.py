import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

INTEGRATION = Path(__file__).resolve().parents[1] / 'integrations/csvjson'
sys.path.insert(0, str(INTEGRATION))
spec = importlib.util.spec_from_file_location('csvjson_adapter', INTEGRATION / 'adapter.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
sys.path.pop(0)


class CSVJSONTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        workspace = self.root / 'workspace'
        workspace.mkdir()
        self.source = workspace / 'csvjson.py'
        self.source.write_text('import csv\nimport json\n')
        self.context = {'run_id': 'test', 'workspace': str(workspace), 'history': []}

    def stage(self, stage):
        output = self.root / stage
        output.mkdir(exist_ok=True)
        result = adapter.execute({**self.context, 'stage': stage, 'output': str(output)})
        self.context['history'].append({'stage': stage, 'status': result['status'], 'artifact_directory': str(output)})
        return result

    def test_delivery_preserves_exact_bytes(self):
        self.assertEqual(self.stage('release')['status'], 'passed')
        self.assertEqual(self.stage('deploy')['status'], 'passed')
        self.assertEqual((self.root / 'deploy/installed/csvjson.py').read_bytes(), self.source.read_bytes())

    def test_tampered_archive_is_rejected(self):
        self.stage('release')
        (self.root / 'release/csvjson.zip').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            self.stage('deploy')

    def test_security_allows_csv_and_string_but_rejects_execution(self):
        self.source.write_text('import csv\nimport io\nimport string\n')
        self.assertEqual(self.stage('security')['status'], 'passed')
        self.source.write_text('import subprocess\nexec("x=1")\n')
        result = self.stage('security')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(result['findings']), 2)

    def test_observation_detects_installed_tampering(self):
        self.stage('release')
        self.stage('deploy')
        (self.root / 'deploy/installed/csvjson.py').write_text('print([])')
        with self.assertRaisesRegex(ValueError, 'differs from deployment receipt'):
            self.stage('observe')

    def test_checks_detect_hardcoded_invalid_delimiter_examples(self):
        self.source.write_text('''import argparse
import sys
p = argparse.ArgumentParser()
p.add_argument('--delimiter', default=',')
p.add_argument('file', nargs='?')
a = p.parse_args()
if len(a.delimiter) != 1 or not a.delimiter.isprintable() or a.delimiter in ['"', ' ', 'Z', '0', 'é', '；']:
    print('invalid delimiter', file=sys.stderr)
    raise SystemExit(2)
print('[]')
''')
        cases = adapter.verify(self.source)
        failures = {c['delimiter'] for c in cases if c['case'] == 'invalid-delimiter-empty-input' and not c['passed']}
        self.assertTrue({'a', 'B', '1', 'Ω', '中', '😀'} <= failures)
