import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

INTEGRATION=Path(__file__).resolve().parents[1]/'integrations/taskboard'
sys.path.insert(0,str(INTEGRATION))
spec=importlib.util.spec_from_file_location('taskboard_adapter',INTEGRATION/'adapter.py')
adapter=importlib.util.module_from_spec(spec); spec.loader.exec_module(adapter)
sys.path.remove(str(INTEGRATION))
REFERENCE=Path(__file__).parent/'fixtures/taskboard_reference'


class TaskboardIntegrationTests(unittest.TestCase):
    def test_blank_is_rejected_with_concrete_missing_requirements(self):
        with tempfile.TemporaryDirectory() as directory:
            cases=adapter.verify(Path(directory))
            self.assertTrue(any(not c['passed'] for c in cases))
            self.assertFalse(next(c for c in cases if c['case']=='multi-file-package')['passed'])

    def test_reference_runs_and_installed_bundle_is_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); workspace=root/'workspace'; shutil.copytree(REFERENCE,workspace)
            context={'workspace':str(workspace),'history':[]}
            for stage in ('verify','security','release','deploy'):
                output=root/stage; output.mkdir()
                result=adapter.execute({**context,'stage':stage,'output':str(output)})
                self.assertEqual(result['status'],'passed',result)
                context['history'].append({'stage':stage,'status':'passed','artifact_directory':str(output)})
            # Removing candidate modules cannot make a broken installed import accidentally work.
            shutil.rmtree(workspace/'taskboard')
            output=root/'observe'; output.mkdir()
            result=adapter.execute({**context,'stage':'observe','output':str(output)})
            self.assertEqual(result['status'],'passed',result)
            self.assertIn('24/24',result['summary'])
            (root/'deploy/installed/taskboard/storage.py').write_text('changed')
            with self.assertRaisesRegex(ValueError,'changed'):
                adapter.execute({**context,'stage':'observe','output':str(output)})

    def test_wrong_state_transition_and_documented_output_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'project'; shutil.copytree(REFERENCE,root)
            p=root/'taskboard/storage.py'; p.write_text(p.read_text().replace('SET completed=1','SET completed=0'))
            self.assertFalse(next(c for c in adapter.verify(root) if c['case']=='complete')['passed'])
            p.write_bytes((REFERENCE/'taskboard/storage.py').read_bytes())
            p=root/'README.md'; p.write_text(p.read_text().replace('"completed":true','"completed":false'))
            self.assertFalse(next(c for c in adapter.verify(root) if c['case']=='documentation-2')['passed'])

    def test_transaction_context_without_close_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'project'
            shutil.copytree(REFERENCE, root)
            storage = root / 'taskboard/storage.py'
            storage.write_text(storage.read_text().replace(
                'with closing(sqlite3.connect(path)) as db, db:',
                'with sqlite3.connect(path) as db:'))
            result = next(case for case in adapter.verify(root)
                          if case['case'] == 'sqlite-connection-lifecycle')
            self.assertFalse(result['passed'])
            self.assertTrue(all(command['still_open'] == 1
                                for command in result['actual']['commands']))
