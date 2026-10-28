"""Independent acceptance checks for opt-in word frequencies."""
import json

from httpstats_checks import request, service, verify as verify_existing


def verify(script):
    results = verify_existing(script)
    # The previously delivered analyze behavior is now the regression baseline.
    for result in results:
        result['baseline'] = True
    examples = [
        ('empty', '', {}),
        ('whitespace', ' \t\n\u00a0\u2003', {}),
        ('repeated', 'red blue red', {'red': 2, 'blue': 1}),
        ('unicode', 'שלום\u00a0世界\u2003שלום', {'שלום': 2, '世界': 1}),
        ('case-punctuation', 'Cat cat Cat cat!', {'Cat': 2, 'cat': 1, 'cat!': 1}),
        ('keys', '__proto__ constructor __proto__', {'__proto__': 2, 'constructor': 1}),
    ]
    with service(script) as port:
        def check(name, payload, expected=None):
            status, content_type, actual = request(port, 'POST', '/analyze', json.dumps(payload).encode())
            expected_status = 200 if expected is not None else 400
            matches = actual == expected if expected is not None else isinstance(actual, dict) and isinstance(actual.get('error'), str) and bool(actual['error'])
            results.append({'case': name, 'baseline': False,
                            'passed': status == expected_status and content_type.split(';')[0] == 'application/json' and matches,
                            'expected': {'status': expected_status, 'body': expected},
                            'actual': {'status': status, 'body': actual}})
        for name, text, frequencies in examples:
            counts = {'characters': len(text), 'words': len(text.split()), 'lines': len(text.splitlines())}
            check(name + '-enabled', {'text': text, 'include_word_frequencies': True}, {**counts, 'word_frequencies': frequencies})
            check(name + '-disabled', {'text': text, 'include_word_frequencies': False}, counts)
        for index, flag in enumerate([None, 0, 1, 'true', 'false', [], {}]):
            check(f'invalid-flag-{index}', {'text': 'a a', 'include_word_frequencies': flag})
    return results
