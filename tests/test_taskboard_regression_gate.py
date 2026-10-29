import importlib.util
from pathlib import Path
import tempfile
import unittest

INTEGRATION = Path(__file__).resolve().parents[1] / 'integrations/taskboard'
spec = importlib.util.spec_from_file_location('taskboard_regression_gate', INTEGRATION / 'regression_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

TEST_SOURCE = '''import sqlite3
import unittest
from taskboard.storage import get_connection

class Lifecycle(unittest.TestCase):
    def test_success(self):
        with get_connection(':memory:') as connection:
            connection.execute('SELECT 1')
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')

    def test_exception(self):
        try:
            with get_connection(':memory:') as connection:
                raise ValueError('expected')
        except ValueError:
            pass
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')

    def test_open_connection(self):
        with get_connection(':memory:') as connection:
            self.assertEqual(connection.execute('SELECT 1').fetchone()[0], 1)
'''


class TaskboardRegressionGateTests(unittest.TestCase):
    def make_project(self, root):
        (root / 'taskboard').mkdir()
        (root / 'taskboard/__init__.py').write_text('')
        source = gate.ORIGINAL.read_text().replace('def get_connection(', '@contextmanager\ndef get_connection(')
        source = source.replace('    return conn', '    try:\n        yield conn\n    finally:\n        conn.close()')
        (root / 'taskboard/storage.py').write_text(source)
        (root / 'tests').mkdir()
        (root / 'tests/test_lifecycle.py').write_text(TEST_SOURCE)

    def test_accepts_real_regressions_without_mutating_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_project(root)
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*.py')}
            case = gate.check_regressions(root)
            self.assertTrue(case['passed'], case)
            self.assertEqual(len(case['actual']['detecting_test_ids']), 2)
            self.assertEqual(before, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*.py')})

    def test_rejects_tests_that_also_pass_original_defect(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_project(root)
            tests = root / 'tests/test_lifecycle.py'
            tests.write_text(TEST_SOURCE.replace('with self.assertRaises(sqlite3.ProgrammingError):\n            connection.execute(\'SELECT 1\')', 'self.assertTrue(True)'))
            case = gate.check_regressions(root)
            self.assertFalse(case['passed'])
            self.assertEqual(case['actual']['detecting_test_ids'], [])

    def test_import_errors_do_not_count_as_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_project(root)
            with (root / 'taskboard/storage.py').open('a') as stream:
                stream.write('\nREPAIRED_ONLY = True\n')
            tests = root / 'tests/test_lifecycle.py'
            tests.write_text('from taskboard.storage import REPAIRED_ONLY\n' + TEST_SOURCE)
            case = gate.check_regressions(root)
            self.assertFalse(case['passed'])
            self.assertTrue(case['actual']['original_defect']['errors'])

    def test_broken_candidate_tests_cannot_pass_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_project(root)
            (root / 'taskboard/storage.py').write_text(gate.ORIGINAL.read_text())
            self.assertFalse(gate.check_regressions(root)['passed'])
