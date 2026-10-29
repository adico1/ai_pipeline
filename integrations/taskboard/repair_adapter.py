"""Taskboard repair adapter: ordinary checks plus generated-test mutation evidence."""
import json
import os
from pathlib import Path

from adapter import execute as execute_project, prior
from regression_gate import check_regressions


def execute(context):
    result = execute_project(context)
    if context['stage'] not in ('verify', 'observe'):
        return result
    root = Path(context['workspace']) if context['stage'] == 'verify' else prior(context, 'deploy') / 'installed'
    output = Path(context['output'])
    case = check_regressions(root)
    (output / 'regression-mutation.json').write_text(json.dumps(case, indent=2))
    cases = json.loads((output / 'scenarios.json').read_text())
    cases.append(case)
    (output / 'scenarios.json').write_text(json.dumps(cases, indent=2))
    failed = [item for item in cases if not item['passed']]
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
