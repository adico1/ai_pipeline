import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

INTEGRATION = Path(__file__).resolve().parents[1] / 'integrations/httpstats'
sys.path.insert(0, str(INTEGRATION))
spec = importlib.util.spec_from_file_location('httpstats_adapter', INTEGRATION / 'adapter.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
sys.path.pop(0)

# Test-only reference, never copied into a factory candidate. It validates the sensor.
REFERENCE_METHODS = '''    def do_POST(self):
        if self.path != '/analyze':
            return self.send_json(404, {'error': 'not found'})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))).decode('utf-8'))
            if not isinstance(body, dict) or not isinstance(body.get('text'), str):
                raise ValueError('text must be a string')
            text = body['text']
        except (ValueError, UnicodeError):
            return self.send_json(400, {'error': 'invalid request'})
        self.send_json(200, {'characters': len(text), 'words': len(text.split()), 'lines': len(text.splitlines())})

    def unsupported(self):
        self.send_json(405, {'error': 'method not allowed'})

    do_PUT = do_PATCH = do_DELETE = do_OPTIONS = unsupported

'''


def reference():
    source = (INTEGRATION / 'baseline_server.py').read_text()
    source = source.replace("        if self.path == '/health':", "        if self.path == '/analyze':\n            return self.unsupported()\n        if self.path == '/health':")
    return source.replace('    def log_message', REFERENCE_METHODS + '    def log_message')


class HTTPStatsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        workspace = self.root / 'workspace'
        workspace.mkdir()
        self.source = workspace / 'server.py'
        self.source.write_text(reference())
        self.context = {'run_id': 'test', 'workspace': str(workspace), 'history': []}

    def stage(self, stage):
        output = self.root / stage
        output.mkdir(exist_ok=True)
        result = adapter.execute({**self.context, 'stage': stage, 'output': str(output)})
        self.context['history'].append({'stage': stage, 'status': result['status'], 'artifact_directory': str(output)})
        return result

    def test_baseline_is_healthy_but_missing_feature_fails(self):
        self.source.write_bytes((INTEGRATION / 'baseline_server.py').read_bytes())
        cases = adapter.verify(self.source)
        self.assertTrue(all(c['passed'] for c in cases if c['baseline']))
        self.assertTrue(all(not c['passed'] for c in cases if not c['baseline']))

    def test_reference_passes_real_http_and_installed_observation(self):
        self.assertEqual(self.stage('verify')['status'], 'passed')
        self.assertEqual(self.stage('security')['status'], 'passed')
        self.assertEqual(self.stage('release')['status'], 'passed')
        self.assertEqual(self.stage('deploy')['status'], 'passed')
        self.assertEqual((self.root / 'deploy/installed/server.py').read_bytes(), self.source.read_bytes())
        self.assertEqual(self.stage('observe')['status'], 'passed')

    def test_sensor_rejects_incorrect_whitespace_counts_and_lax_input(self):
        self.source.write_text(reference().replace('len(text.split())', "len(text.split(' '))"))
        cases = adapter.verify(self.source)
        self.assertTrue(any(not c['passed'] and c['case'].startswith('text-') for c in cases))
        self.source.write_text(reference().replace('400,', '200,'))
        self.assertTrue(any(not c['passed'] and c['case'].startswith('invalid-body-') for c in adapter.verify(self.source)))

    def test_tampering_and_unapproved_imports_are_rejected(self):
        self.stage('release')
        archive = self.root / 'release/httpstats.zip'
        original = archive.read_bytes()
        archive.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            self.stage('deploy')
        archive.write_bytes(original)
        self.stage('deploy')
        (self.root / 'deploy/installed/server.py').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'differs from deployment receipt'):
            self.stage('observe')
        self.source.write_text('import subprocess\n')
        self.assertEqual(self.stage('security')['status'], 'failed')

    def test_service_is_stopped_when_checks_raise(self):
        from httpstats_checks import service, request
        with self.assertRaisesRegex(RuntimeError, 'test interruption'):
            with service(self.source) as port:
                self.assertEqual(request(port, 'GET', '/health')[0], 200)
                raise RuntimeError('test interruption')
        with self.assertRaises(OSError):
            request(port, 'GET', '/health')
