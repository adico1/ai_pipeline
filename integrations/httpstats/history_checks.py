"""Black-box persistence, compatibility and executable documentation checks."""
import json
from pathlib import Path
import re
import tempfile

from httpstats_checks import request, service
from utf8_checks import verify as verify_existing


def record(results, name, passed, expected, actual):
    results.append({'case': name, 'baseline': False, 'passed': bool(passed),
                    'expected': expected, 'actual': actual})


def exchange(results, port, name, method, path, payload, status, expected=None):
    body = json.dumps(payload).encode() if payload is not None else b''
    code, content_type, actual = request(port, method, path, body)
    matches = actual == expected if expected is not None else isinstance(actual, dict) and isinstance(actual.get('error'), str) and bool(actual['error'])
    record(results, name, code == status and content_type.split(';')[0] == 'application/json' and matches,
           {'status': status, 'body': expected}, {'status': code, 'body': actual})
    return actual


def verify(script):
    results = verify_existing(script)
    for case in results:
        case['baseline'] = True
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'saved.sqlite3'
            options = {'directory': root, 'extra_args': ('--database', str(database))}
            saved = {'id': 1, 'text': 'é é', 'analysis': {'characters': 3, 'words': 2, 'lines': 1,
                     'word_frequencies': {'é': 2}, 'utf8_bytes': 5}}
            second = {'id': 2, 'text': "'; DROP TABLE analyses; --", 'analysis': {'characters': 26, 'words': 5, 'lines': 1}}
            # Compute the fixed adversarial input length independently of candidate logic.
            second['analysis']['characters'] = len(second['text'])
            with service(script, **options) as port:
                exchange(results, port, 'history-missing', 'GET', '/analyses/1', None, 404)
                exchange(results, port, 'history-save', 'POST', '/analyses', {'text': 'é é', 'include_word_frequencies': True, 'include_utf8_bytes': True}, 201, saved)
                exchange(results, port, 'history-get', 'GET', '/analyses/1', None, 200, saved)
                exchange(results, port, 'history-sql-text', 'POST', '/analyses', {'text': second['text']}, 201, second)
                for index, payload in enumerate([{}, [], {'text': 5}, {'text': 'x', 'include_utf8_bytes': 1}, {'text': 'x', 'include_word_frequencies': 'true'}, {'text': '\ud800'}]):
                    exchange(results, port, f'history-invalid-{index}', 'POST', '/analyses', payload, 400)
                code, _, body = request(port, 'POST', '/analyses', b'{')
                record(results, 'history-malformed-json', code == 400 and isinstance(body, dict) and bool(body.get('error')), 400, code)
                exchange(results, port, 'analyze-remains-stateless', 'POST', '/analyze', {'text': 'not saved'}, 200, {'characters': 9, 'words': 2, 'lines': 1})
                exchange(results, port, 'history-no-implicit-save', 'GET', '/analyses/3', None, 404)
                for suffix in ['0', '-1', 'abc', '1/extra', '99999999999999999999999999', '1%20OR%201=1']:
                    exchange(results, port, 'history-bad-id-' + suffix, 'GET', '/analyses/' + suffix, None, 404)
                for method, path in [('GET', '/analyses'), ('PUT', '/analyses'), ('DELETE', '/analyses/1'), ('POST', '/analyses/1')]:
                    exchange(results, port, f'history-method-{method}-{path}', method, path, None, 405)
            record(results, 'history-real-sqlite', database.exists() and database.read_bytes().startswith(b'SQLite format 3\x00'), 'SQLite database file', database.exists())
            with service(script, **options) as port:
                exchange(results, port, 'history-survives-restart', 'GET', '/analyses/1', None, 200, saved)
                exchange(results, port, 'history-sql-text-survives', 'GET', '/analyses/2', None, 200, second)
                empty = {'id': 3, 'text': '', 'analysis': {'characters': 0, 'words': 0, 'lines': 0}}
                exchange(results, port, 'history-continues-after-restart', 'POST', '/analyses', {'text': ''}, 201, empty)
            with service(script, directory=root, extra_args=('--database', str(root/'other.sqlite3'))) as port:
                exchange(results, port, 'history-database-isolation', 'GET', '/analyses/1', None, 404)
            with service(script, directory=root) as port:
                exchange(results, port, 'history-default-path', 'GET', '/health', None, 200, {'status': 'ok'})
            record(results, 'history-default-sqlite', (root/'httpstats.sqlite3').exists(), 'default database initialized', (root/'httpstats.sqlite3').exists())
    except (OSError, RuntimeError, ValueError) as exc:
        record(results, 'history-service-error', False, 'working persistent history service', str(exc))
    return results


def verify_documentation(script, readme):
    """Execute a declarative README example; never evaluate prose or shell code."""
    results = []
    try:
        text = Path(readme).read_text()
        matches = re.findall(r'```json history-examples\s*\n(.*?)\n```', text, re.S)
        if len(matches) != 1:
            raise ValueError('README requires exactly one fenced json history-examples block')
        examples = json.loads(matches[0])
        if not isinstance(examples, list) or len(examples) != 2:
            raise ValueError('history-examples must contain exactly two request/response examples')
        required = [('POST', '/analyses', 201), ('GET', '/analyses/1', 200)]
        with tempfile.TemporaryDirectory() as directory:
            with service(script, directory=directory, extra_args=('--database', str(Path(directory)/'docs.sqlite3'))) as port:
                for index, (example, (method, path, status)) in enumerate(zip(examples, required)):
                    if (example.get('method'), example.get('path'), example.get('status')) != (method, path, status):
                        raise ValueError('Examples must save a new analysis then retrieve ID 1 from a fresh database')
                    exchange(results, port, f'documentation-example-{index}', method, path, example.get('json'), status, example['response'])
        record(results, 'documentation-startup', '--database' in text and 'curl' in text, 'README explains startup and curl usage', '--database' in text and 'curl' in text)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        record(results, 'documentation-contract', False, 'executable save/retrieve README examples', str(exc))
    return results
