"""Independent HTTP acceptance checks for opt-in UTF-8 byte counts."""
import json
from httpstats_checks import request, service
from word_frequency_checks import verify as verify_existing


def verify(script):
    results = verify_existing(script)
    for result in results:
        result['baseline'] = True
    with service(script) as port:
        def check(name, payload, expected=None):
            status, content_type, actual = request(port, 'POST', '/analyze', json.dumps(payload).encode())
            expected_status = 200 if expected is not None else 400
            matches = actual == expected if expected is not None else isinstance(actual, dict) and isinstance(actual.get('error'), str) and bool(actual['error'])
            results.append({'case': name, 'baseline': False,
                            'passed': status == expected_status and content_type.split(';')[0] == 'application/json' and matches,
                            'expected': {'status': expected_status, 'body': expected},
                            'actual': {'status': status, 'body': actual}})
        examples = [('', 0), ('abc', 3), ('é', 2), ('😀', 4), ('e\u0301', 3), ('שלום', 8), ('a\u00a0a', 4), ('\r\n', 2)]
        for index, (text, byte_count) in enumerate(examples):
            counts = {'characters': len(text), 'words': len(text.split()), 'lines': len(text.splitlines())}
            check(f'utf8-{index}-on', {'text': text, 'include_utf8_bytes': True}, {**counts, 'utf8_bytes': byte_count})
            check(f'utf8-{index}-off', {'text': text, 'include_utf8_bytes': False}, counts)
        check('utf8-with-frequencies', {'text': 'é é', 'include_utf8_bytes': True, 'include_word_frequencies': True},
              {'characters': 3, 'words': 2, 'lines': 1, 'utf8_bytes': 5, 'word_frequencies': {'é': 2}})
        for index, flag in enumerate([None, 0, 1, 'true', 'false', [], {}]):
            check(f'utf8-invalid-flag-{index}', {'text': 'a', 'include_utf8_bytes': flag})
        check('utf8-unpaired-surrogate', {'text': '\ud800', 'include_utf8_bytes': True})
        check('utf8-still-healthy', {'text': 'ok', 'include_utf8_bytes': True}, {'characters': 2, 'words': 1, 'lines': 1, 'utf8_bytes': 2})
    return results
