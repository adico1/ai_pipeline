"""Describe recorded check differences without inferring application defects."""

import json


def describe_check(evidence):
    """Render check data literally; case names never determine the diagnosis."""
    detail = evidence['detail']
    label = f"{evidence['stage']} check {json.dumps(detail.get('case', 'result'))}"
    if 'expected' not in detail or 'actual' not in detail:
        return f"{label} reported {evidence['status']}: {json.dumps(detail, ensure_ascii=False)}"
    expected, actual = detail['expected'], detail['actual']
    # Project command checks wrap the observed JSON response in an exit envelope.
    if isinstance(expected, (dict, list)) and isinstance(actual, dict) and 'body' in actual and 'exit_code' in actual:
        actual = actual['body']
    differences = []

    def compare(wanted, observed, path):
        if not isinstance(wanted, (dict, list)) and type(wanted) is type(observed) and wanted == observed:
            return
        if isinstance(wanted, dict) and isinstance(observed, dict):
            for key in sorted(wanted.keys() | observed.keys()):
                child = path + '/' + key.replace('~', '~0').replace('/', '~1')
                if key not in observed:
                    differences.append(f'{child}: missing; expected {json.dumps(wanted[key])}')
                elif key not in wanted:
                    differences.append(f'{child}: unexpected value {json.dumps(observed[key])}')
                else:
                    compare(wanted[key], observed[key], child)
        elif isinstance(wanted, list) and isinstance(observed, list) and len(wanted) == len(observed):
            for index, (left, right) in enumerate(zip(wanted, observed)):
                compare(left, right, f'{path}/{index}')
        else:
            differences.append(f'{path or "/"}: expected {json.dumps(wanted, ensure_ascii=False)}; observed {json.dumps(observed, ensure_ascii=False)}')

    compare(expected, actual, '')
    if not differences:
        return f'{label} reported {evidence["status"]}; the supplied expected/actual values match. Consult the full check evidence.'
    suffix = f'; {len(differences) - 20} more differences in attached evidence' if len(differences) > 20 else ''
    return f'{label}: ' + '; '.join(differences[:20]) + suffix
