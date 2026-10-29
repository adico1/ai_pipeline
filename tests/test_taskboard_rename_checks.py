import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

INTEGRATION = Path(__file__).resolve().parents[1] / 'integrations/taskboard'
sys.path.insert(0, str(INTEGRATION))
spec = importlib.util.spec_from_file_location('taskboard_rename_checks', INTEGRATION / 'rename_checks.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)
sys.path.remove(str(INTEGRATION))
REFERENCE = Path(__file__).parent / 'fixtures/taskboard_reference'


def reference_with_rename(root):
    shutil.copytree(REFERENCE, root)
    cli = root / 'taskboard/__main__.py'
    text = cli.read_text().replace('args=parser.parse_args()', "rename=sub.add_parser('rename')\nrename.add_argument('id')\nrename.add_argument('title')\nargs=parser.parse_args()")
    text = text.replace("getattr(args,'title',getattr(args,'id',None))", "(args.id,args.title) if args.command=='rename' else getattr(args,'title',getattr(args,'id',None))")
    cli.write_text(text)
    storage = root / 'taskboard/storage.py'
    storage.write_text(storage.read_text().replace("        elif command == 'complete':", """        elif command == 'rename':
            key=identifier(value[0]); new_title=title(value[1])
            if db.execute('UPDATE tasks SET title=? WHERE id=?',(new_title,key)).rowcount == 0:
                raise ValueError('missing id')
            row=db.execute('SELECT * FROM tasks WHERE id=?',(key,)).fetchone()
        elif command == 'complete':"""))
    initial = {'id': 1, 'title': 'old', 'completed': False}
    done = {**initial, 'completed': True}
    renamed = {**done, 'title': 'new'}
    examples = [{'args': ['add','old'], 'stdout': initial},
                {'args': ['complete','1'], 'stdout': done},
                {'args': ['rename','1','new'], 'stdout': renamed},
                {'args': ['list'], 'stdout': [renamed]}]
    with (root / 'README.md').open('a') as stream:
        stream.write('\n```json taskboard-rename-examples\n' + json.dumps(examples) + '\n```\n')


class TaskboardRenameChecksTests(unittest.TestCase):
    def test_reference_passes_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'project'
            reference_with_rename(root)
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            cases = checks.verify_rename(root)
            self.assertTrue(all(case['passed'] for case in cases), cases)
            self.assertEqual(before, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_detects_lost_completed_state_and_connection_leak(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'project'
            reference_with_rename(root)
            path = root / 'taskboard/storage.py'
            path.write_text(path.read_text().replace('SET title=? WHERE id=?', 'SET title=?, completed=0 WHERE id=?').replace('with closing(sqlite3.connect(path)) as db, db:', 'with sqlite3.connect(path) as db:'))
            cases = {case['case']: case for case in checks.verify_rename(root)}
            self.assertFalse(cases['rename-completed-stays-completed']['passed'])
            self.assertFalse(cases['rename-connection-lifecycle']['passed'])

    def test_rejects_missing_feature_and_false_documentation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'project'
            shutil.copytree(REFERENCE, root)
            cases = {case['case']: case for case in checks.verify_rename(root)}
            self.assertFalse(cases['rename-trim']['passed'])
            self.assertFalse(cases['rename-documentation']['passed'])
            shutil.rmtree(root)
            reference_with_rename(root)
            readme = root / 'README.md'
            readme.write_text(readme.read_text().replace('"title": "new"', '"title": "wrong"'))
            cases = {case['case']: case for case in checks.verify_rename(root)}
            self.assertFalse(cases['rename-documentation-2']['passed'])
