"""Existing Taskboard checks plus rename behavior and executable documentation."""
import json
import os
from pathlib import Path
import re

from adapter import execute as execute_project, prior
from rename_checks import verify_rename


def execute(context):
    result = execute_project(context)
    if context['stage'] not in ('verify', 'observe'):
        return result
    output = Path(context['output'])
    root = Path(context['workspace']) if context['stage'] == 'verify' else prior(context, 'deploy') / 'installed'
    cases = json.loads((output / 'scenarios.json').read_text())
    cases.extend(verify_rename(root))
    log = (output / 'generated-tests.log').read_text()
    count = re.search(r'Ran (\d+) tests?', log)
    cases.append({'case': 'rename-generated-test-count', 'baseline': False,
                  'passed': count is not None and int(count[1]) >= 8,
                  'expected': 'Preserve five baseline tests and add at least three meaningful rename tests',
                  'actual': int(count[1]) if count else 0})
    (output / 'scenarios.json').write_text(json.dumps(cases, indent=2))
    failed = [case for case in cases if not case['passed']]
    return {**result, 'status': 'failed' if failed else 'passed', 'failed_cases': failed,
            'summary': f'{len(cases) - len(failed)}/{len(cases)} project checks passed.'}


if __name__ == '__main__':
    context = json.loads(Path(os.environ['FACTORY_CONTEXT']).read_text())
    try:
        result = execute(context)
    except Exception as exc:
        result = {'status': 'failed', 'summary': f'{type(exc).__name__}: {exc}'}
    (Path(context['output']) / 'result.json').write_text(json.dumps(result, indent=2))
    print(result['summary'])
    raise SystemExit(result['status'] != 'passed')
