import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ai_pipeline.cli import demo_config
from ai_pipeline.engine import Factory, FactoryError, load_config, write_json
from ai_pipeline.crewai_adapter import current_changed_source
from ai_pipeline.project_bundle import build_bundle, install_bundle, source_files


class BlankProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = demo_config(self.root/'config.json')
        data = json.loads(self.config.read_text()); data.pop('demo'); data['starting_point']='blank'
        write_json(self.config, data)

    def test_blank_workspace_has_empty_commit_and_reviews_new_modules(self):
        factory = Factory(self.root/'runs'); state = factory.create(self.config, 'Create a package')
        workspace = factory.directory(state['id'])/'workspace'
        tracked = subprocess.check_output(['git','-C',str(workspace),'ls-tree','-r','--name-only',state['base_commit']],text=True)
        self.assertEqual(tracked, '')
        self.assertEqual([p.name for p in workspace.iterdir()], ['.git'])
        (workspace/'package').mkdir(); (workspace/'package/core.py').write_text('VALUE = 3\n')
        (workspace/'.env').write_text('do not include')
        snapshot = current_changed_source({'workspace':str(workspace),'base_commit':state['base_commit']})
        self.assertEqual(snapshot, [{'path':'package/core.py','current_text':'VALUE = 3\n'}])

    def test_blank_configuration_rejects_ambiguous_source(self):
        data = json.loads(self.config.read_text()); data['repository']='some-repo'
        write_json(self.config,data)
        with self.assertRaisesRegex(FactoryError,'cannot also specify'):
            load_config(self.config)

    def test_blank_cli_template_needs_no_repository(self):
        output = self.root/'blank.json'
        subprocess.run([sys.executable,'-m','ai_pipeline.cli','--state-dir',str(self.root/'state'),'init','--blank','--name','new-app','--output',str(output)],check=True,capture_output=True)
        data=json.loads(output.read_text())
        self.assertEqual(data['starting_point'],'blank'); self.assertNotIn('repository',data)
        self.assertEqual(data['name'],'new-app')

    def test_crew_iteration_budget_is_bounded(self):
        data=json.loads(self.config.read_text()); data['stages']['implement']={'backend':'crewai','crewai':{'max_iter':41}}
        write_json(self.config,data)
        with self.assertRaisesRegex(FactoryError,'max_iter'):
            load_config(self.config)


class ProjectBundleTests(unittest.TestCase):
    def test_multifile_roundtrip_and_archive_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'source'; (source/'app').mkdir(parents=True)
            (source/'app/__init__.py').write_text('from .core import answer\n')
            (source/'app/core.py').write_text('answer = 42\n')
            release=root/'release'; release.mkdir()
            manifest=build_bundle(source,release,['app'])
            installed=root/'installed'; install_bundle(release,installed)
            self.assertEqual(source_files(installed,['app']),manifest['files'])
            (release/'project.zip').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'digest'):
                install_bundle(release,root/'bad')

    def test_rejects_symlinks_runtime_files_and_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'app').mkdir()
            (root/'app/cache.sqlite3').write_bytes(b'data')
            with self.assertRaisesRegex(ValueError,'Unsupported'):
                source_files(root,['app'])
            (root/'app/cache.sqlite3').unlink(); (root/'app/link.py').symlink_to(root/'outside.py')
            with self.assertRaisesRegex(ValueError,'Symlinks'):
                source_files(root,['app'])
            with self.assertRaisesRegex(ValueError,'relative'):
                source_files(root,['../outside'])
