"""Prove the acceptance sensor rejects missing features and semantic mutations."""
from pathlib import Path
import sys
import tempfile
import unittest

from test_httpstats_integration import INTEGRATION, reference

sys.path.insert(0, str(INTEGRATION))
from word_frequency_checks import verify
sys.path.pop(0)


def frequency_reference():
    # Test fixture only; never installed into a candidate repository.
    source = reference().replace("            text = body['text']", """            text = body['text']
            flag = body.get('include_word_frequencies', False)
            if not isinstance(flag, bool):
                raise ValueError('invalid flag')""")
    return source.replace("        self.send_json(200, {'characters': len(text), 'words': len(text.split()), 'lines': len(text.splitlines())})", """        result = {'characters': len(text), 'words': len(text.split()), 'lines': len(text.splitlines())}
        if flag:
            result['word_frequencies'] = {token: text.split().count(token) for token in text.split()}
        self.send_json(200, result)""")


class WordFrequencySensorTests(unittest.TestCase):
    def check_source(self, source):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'server.py'
            script.write_text(source)
            return verify(script)

    def test_existing_feature_is_baseline_but_new_feature_is_missing(self):
        cases = self.check_source(reference())
        self.assertEqual(len(cases), 63)
        self.assertEqual(sum(c['baseline'] for c in cases), 44)
        self.assertTrue(all(c['passed'] for c in cases if c['baseline']))
        self.assertTrue(any(not c['passed'] for c in cases))

    def test_reference_passes_and_semantic_mutations_fail(self):
        self.assertTrue(all(c['passed'] for c in self.check_source(frequency_reference())))
        mutations = [
            ('if flag:', 'if True:'),
            ('isinstance(flag, bool)', 'isinstance(flag, (bool, int))'),
            ('text.split().count(token)', '1'),
            ('for token in text.split()', 'for token in text.lower().split()'),
        ]
        for before, after in mutations:
            with self.subTest(mutation=after):
                cases = self.check_source(frequency_reference().replace(before, after))
                self.assertTrue(any(not c['passed'] for c in cases))
