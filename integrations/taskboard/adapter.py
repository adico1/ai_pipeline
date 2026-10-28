"""Trusted checks and multi-file source delivery for the blank-project trial."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ai_pipeline.project_bundle import build_bundle, install_bundle, source_files
from checks import verify

INCLUDES = ['taskboard', 'tests', 'README.md', 'pyproject.toml', '.gitignore']


def prior(context, stage):
    return Path(next(a['artifact_directory'] for a in reversed(context['history']) if a['stage'] == stage and a['status'] == 'passed'))


def execute(context):
    workspace, output = Path(context['workspace']), Path(context['output'])
    stage = context['stage']
    if stage in ('verify', 'observe'):
        root = workspace if stage == 'verify' else prior(context, 'deploy')/'installed'
        if stage == 'observe':
            manifest = json.loads((prior(context, 'deploy')/'deployment.json').read_text())
            if source_files(root, INCLUDES) != manifest['files']:
                raise ValueError('Installed source changed after deployment')
        cases = verify(root)
        # Run the generated tests on an isolated copy so test side effects cannot alter the candidate.
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory)/'project'
            shutil.copytree(root, copied, ignore=shutil.ignore_patterns('.git', '__pycache__', '.venv'))
            result = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=copied,
                                    env={**os.environ, 'PYTHONPATH': str(copied), 'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, text=True, timeout=45)
            log = result.stdout + result.stderr
            (output/'generated-tests.log').write_text(log)
            import re
            count = re.search(r'Ran (\d+) tests?', log)
            cases.append({'case': 'generated-tests', 'baseline': False, 'passed': result.returncode == 0 and count is not None and int(count[1]) >= 3,
                          'expected': 'At least 3 generated unittest tests pass', 'actual': log[-2500:]})
        (output/'scenarios.json').write_text(json.dumps(cases, indent=2, ensure_ascii=False))
        failed = [c for c in cases if not c['passed']]
        return {'status': 'failed' if failed else 'passed', 'summary': f'{len(cases)-len(failed)}/{len(cases)} project checks passed.', 'failed_cases': failed, 'baseline_tests_passed': True}
    if stage == 'security':
        files = source_files(workspace, INCLUDES)
        violations = []
        allowed = {'argparse', 'json', 'sqlite3', 'sys', 'pathlib', 'contextlib', 're', 'unittest', 'tempfile', 'subprocess', 'os', 'taskboard'}
        for name in files:
            if not name.endswith('.py'):
                continue
            tree = ast.parse((workspace/name).read_text())
            for node in ast.walk(tree):
                imports = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or 'taskboard'] if isinstance(node, ast.ImportFrom) else []
                for module in imports:
                    if module.split('.')[0] not in allowed and not (isinstance(node, ast.ImportFrom) and node.level):
                        violations.append(f'{name}: unapproved import {module}')
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {'eval', 'exec', '__import__'}:
                    violations.append(f'{name}: dynamic code execution')
        return {'status': 'failed' if violations else 'passed', 'summary': 'Source packaging and limited static import policy checked; not a comprehensive security audit.', 'findings': violations}
    if stage == 'release':
        manifest = build_bundle(workspace, output, INCLUDES)
        return {'status': 'passed', 'summary': f'Packaged {len(manifest["files"])} files with per-file hashes.', **manifest}
    if stage == 'deploy':
        release = prior(context, 'release')
        manifest = json.loads((release/'manifest.json').read_text())
        if source_files(workspace, INCLUDES) != manifest['files']:
            raise ValueError('Candidate differs from release manifest')
        install_bundle(release, output/'installed')
        (output/'deployment.json').write_text(json.dumps(manifest, indent=2))
        return {'status': 'passed', 'summary': 'Installed complete source bundle into separate directory; observation runs from an unrelated working directory.', 'files': manifest['files']}
    raise ValueError(f'Unsupported stage: {stage}')


if __name__ == '__main__':
    context = json.loads(Path(os.environ['FACTORY_CONTEXT']).read_text())
    try:
        result = execute(context)
    except Exception as exc:
        result = {'status': 'failed', 'summary': f'{type(exc).__name__}: {exc}'}
    (Path(context['output'])/'result.json').write_text(json.dumps(result, indent=2))
    print(result['summary'])
    raise SystemExit(result['status'] != 'passed')
