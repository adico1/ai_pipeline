"""Independent black-box checks against real, temporary loopback HTTP processes."""
from contextlib import contextmanager
import http.client
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time


@contextmanager
def service(script):
    with tempfile.TemporaryDirectory() as temp:
        log = Path(temp) / 'service.log'
        with log.open('w') as output:
            process = subprocess.Popen([sys.executable, str(Path(script).resolve()), '--port', '0'],
                                       cwd=temp, stdout=output, stderr=output)
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    lines = log.read_text(errors='replace').splitlines()
                    if lines and lines[0].startswith('PORT='):
                        port = int(lines[0][5:])
                        break
                    if process.poll() is not None:
                        raise RuntimeError('Service exited before readiness: ' + log.read_text()[-1000:])
                    time.sleep(0.02)
                else:
                    raise RuntimeError('Service readiness timeout')
                yield port
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)


def request(port, method, path, body=b''):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
    try:
        connection.request(method, path, body, {'Content-Type': 'application/json'})
        response = connection.getresponse()
        data = response.read()
        try:
            decoded = json.loads(data)
        except (ValueError, UnicodeError):
            decoded = data.decode('utf-8', errors='replace')[:200]
        return response.status, response.getheader('Content-Type', ''), decoded
    finally:
        connection.close()


def verify(script):
    results = []
    with service(script) as port:
        def check(name, method, path, body, status, expected=None, baseline=False):
            try:
                code, content_type, actual = request(port, method, path, body)
                payload_ok = actual == expected if expected is not None else isinstance(actual, dict) and isinstance(actual.get('error'), str) and bool(actual['error'])
                passed = code == status and content_type.split(';')[0].strip() == 'application/json' and payload_ok
                observed = {'status': code, 'body': actual}
            except (OSError, http.client.HTTPException) as exc:
                passed, observed = False, {'error': str(exc)}
            results.append({'case': name, 'baseline': baseline, 'passed': passed,
                            'expected': {'status': status, 'body': expected if expected is not None else 'nonempty JSON error'}, 'actual': observed})

        check('health-before', 'GET', '/health', b'', 200, {'status': 'ok'}, True)
        check('unknown-get', 'GET', '/missing', b'', 404, baseline=True)
        texts = ['', ' ', '\t\n\r', 'hello world', 'hello   world', 'a\tb\nc',
                 'one\u00a0two\u2003three', 'שלום עולם', '你好 世界', '😀 café',
                 'a\nb\n', 'a\r\nb\r\n', 'a\rb', '\n', 'a\u2028b', 'e\u0301',
                 'α\u0085β', 'a' * 4096, 'a\x00b']
        for i, text in enumerate(texts):
            expected = {'characters': len(text), 'words': len(text.split()), 'lines': len(text.splitlines())}
            check(f'text-{i}', 'POST', '/analyze', json.dumps({'text': text}, ensure_ascii=False).encode(), 200, expected)
        check('extra-fields-ignored', 'POST', '/analyze', b'{"text":"a b","other":42}', 200,
              {'characters': 3, 'words': 2, 'lines': 1})
        for i, body in enumerate([b'', b'{', b'not json', b'{"text":}', b'\xff',
                                  b'{}', b'[]', b'null', b'"text"', b'42',
                                  b'{"text":null}', b'{"text":12}', b'{"text":true}',
                                  b'{"text":[]}', b'{"text":{}}']):
            check(f'invalid-body-{i}', 'POST', '/analyze', body, 400)
        for method in ['GET', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']:
            check(f'method-{method}', method, '/analyze', b'{"text":"a"}', 405)
        check('unknown-post', 'POST', '/missing', b'{"text":"a"}', 404)
        check('health-after-errors', 'GET', '/health', b'', 200, {'status': 'ok'}, True)
    return results
