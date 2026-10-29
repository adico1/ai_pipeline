"""Repair-specific mutation check for the recorded Taskboard connection leak."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ORIGINAL = Path(__file__).with_name('original_storage.txt')
RUNNER = Path(__file__).with_name('regression_runner.py')


def run_tests(project):
    result = subprocess.run(
        [sys.executable, '-B', str(RUNNER)], cwd=project,
        env={**os.environ, 'PYTHONPATH': str(project), 'PYTHONDONTWRITEBYTECODE': '1'},
        capture_output=True, text=True, timeout=45,
    )
    if result.returncode:
        raise ValueError(f'Test runner failed: {result.stderr[-1500:]}')
    return json.loads(result.stdout)


def check_regressions(root):
    """Only copies are mutated; the candidate and installed bundle stay untouched."""
    evidence = {'original_storage_sha256': hashlib.sha256(ORIGINAL.read_bytes()).hexdigest()}
    try:
        with tempfile.TemporaryDirectory() as directory:
            for variant in ('repaired', 'original_defect'):
                copied = Path(directory) / variant
                shutil.copytree(root, copied, ignore=shutil.ignore_patterns('.git', '__pycache__', '.venv'))
                if variant == 'original_defect':
                    (copied / 'taskboard/storage.py').write_bytes(ORIGINAL.read_bytes())
                evidence[variant] = run_tests(copied)
        repaired, original = evidence['repaired'], evidence['original_defect']
        # Require genuine assertions about closed handles, not import errors or
        # unrelated behavioral failures caused by restoring an incompatible module.
        detected = {failure['id'] for failure in original['failures']
                    if 'ProgrammingError not raised' in failure['traceback']}
        evidence['detecting_test_ids'] = sorted(detected)
        clean = all(not repaired[key] for key in
                    ('failures', 'errors', 'skipped', 'expected_failures', 'unexpected_successes'))
        passed = (clean and repaired['tests_run'] >= 3 and not original['errors']
                  and len(detected) >= 2 and detected <= set(repaired['passed_ids']))
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        evidence['error'] = f'{type(exc).__name__}: {exc}'
        passed = False
    return {'case': 'generated-lifecycle-regressions', 'baseline': False, 'passed': passed,
            'expected': 'Generated tests pass repaired source; at least two closed-handle assertions '
                        '(success and exception paths) fail with ProgrammingError not raised '
                        'against original leaking storage. Import errors do not count.',
            'actual': evidence}
