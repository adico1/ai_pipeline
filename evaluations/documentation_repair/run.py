"""One live writer-only repair control on an isolated saved Taskboard candidate."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ai_pipeline.cli import load_environment
from ai_pipeline.crewai_adapter import build_crew, run_candidate_checks, CandidateStalled, ImplementationIncomplete
from ai_pipeline.engine import Factory, digest_tree

BLOCK = re.compile(r'```json taskboard-rename-examples\s*\n.*?\n```', re.S)


def files(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file() and '__pycache__' not in path.parts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args()
    run = Factory(ROOT / '.factory').directory(args.source_run)
    source = run / 'workspace'
    original_digest = digest_tree(source)
    state = json.loads((run / 'state.json').read_text())
    config = json.loads((run / 'config.json').read_text())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / 'workspace'
    workspace.mkdir()
    for name in ('taskboard', 'tests'):
        shutil.copytree(source / name, workspace / name, ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('README.md', 'pyproject.toml', '.gitignore'):
        shutil.copy2(source / name, workspace / name)
    before = files(workspace)
    readme_before = (workspace / 'README.md').read_text()
    assert len(BLOCK.findall(readme_before)) == 1
    frozen = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
              for name in subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT, text=True).split('\0') if name}
    context = {'stage': 'implement', 'workspace': str(workspace), 'output': str(output),
               'task': (run / 'task.txt').read_text() + '\nThis is a focused repair control: correct only the json taskboard-rename-examples block in README.md. Preserve all other README text and all other files. Inspect source and call check_current_candidate, act on current failure feedback, then recheck. Do not rewrite application code or tests.\n',
               'history': [attempt for attempt in state['attempts'] if attempt['status'] == 'passed'],
               'crewai': config['stages']['implement']['crewai'],
               'checks': {name: config['stages'][name] for name in ('verify', 'security')}}
    report = {'factory_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'source_run': args.source_run, 'original_digest': original_digest,
              'model_config': context['crewai'], 'live_writer_executed': False, 'operator_retries': 0,
              'manual_candidate_edits': 0}
    preflight = json.loads(run_candidate_checks(context))
    report['preflight'] = preflight
    verify, security = preflight['checks']
    failures = verify['report'].get('failure_groups', [])
    assert verify['status'] == 'failed' and security['status'] == 'passed'
    assert len(failures) == 1 and failures[0]['example']['case'] == 'rename-documentation'
    assert failures[0]['example']['actual']['commands'] == ['add', 'add', 'complete', 'rename', 'rename', 'list']
    if not args.preflight_only:
        load_environment(ROOT / '.env')
        os.environ['CREWAI_STORAGE_DIR'] = str(output / 'storage')
        report['live_writer_executed'] = True
        try:
            crew = build_crew(context)
            result = crew.tasks[0].execute_sync(agent=crew.agents[0])
            report['writer_result'] = result.raw
        except (Exception, CandidateStalled, ImplementationIncomplete) as exc:
            report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
        # External read-only validation does not resume or retry the writer.
        report['postflight'] = json.loads(run_candidate_checks(context))
    after = files(workspace)
    report['changed_files'] = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
    readme_after = (workspace / 'README.md').read_text()
    report['outside_block_unchanged'] = (len(BLOCK.findall(readme_after)) == 1 and
        BLOCK.sub('<RENAME_EXAMPLES>', readme_before) == BLOCK.sub('<RENAME_EXAMPLES>', readme_after))
    report['original_unchanged'] = digest_tree(source) == original_digest
    report['frozen_inputs_unchanged'] = all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == value for name, value in frozen.items())
    report['passed'] = (report['live_writer_executed'] and 'error' not in report and
        report['changed_files'] == ['README.md'] and report['outside_block_unchanged'] and
        report['original_unchanged'] and report['frozen_inputs_unchanged'] and
        all(check['status'] == 'passed' for check in report['postflight']['checks']))
    report['limitations'] = ['One guided writer-only repair fixture, not a full lifecycle or repeatability trial.',
                             'The narrow repair task explicitly restricts edits to the README block.']
    (output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('passed', 'live_writer_executed', 'changed_files', 'outside_block_unchanged', 'original_unchanged')}))


if __name__ == '__main__':
    main()
