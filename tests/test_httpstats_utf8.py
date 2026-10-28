"""Validate the byte-count sensor independently of CrewAI's candidate."""
from pathlib import Path
import sys
import tempfile
import unittest
from test_httpstats_integration import INTEGRATION
from test_httpstats_word_frequencies import frequency_reference
sys.path.insert(0, str(INTEGRATION))
from utf8_checks import verify
sys.path.pop(0)


def utf8_reference():
    return frequency_reference().replace("        self.send_json(200, result)", """        byte_flag = body.get('include_utf8_bytes', False)
        if not isinstance(byte_flag, bool):
            return self.send_json(400, {'error': 'invalid flag'})
        if byte_flag:
            try:
                result['utf8_bytes'] = len(text.encode('utf-8'))
            except UnicodeEncodeError:
                return self.send_json(400, {'error': 'invalid unicode'})
        self.send_json(200, result)""")


class UTF8SensorTests(unittest.TestCase):
    def cases(self, source):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'server.py'
            script.write_text(source)
            return verify(script)

    def test_previous_features_pass_but_missing_byte_count_fails(self):
        results = self.cases(frequency_reference())
        self.assertEqual(len(results), 89)
        self.assertEqual(sum(c['baseline'] for c in results), 63)
        self.assertTrue(all(c['passed'] for c in results if c['baseline']))
        self.assertTrue(any(not c['passed'] for c in results))

    def test_reference_passes_and_wrong_counts_or_validation_fail(self):
        self.assertTrue(all(c['passed'] for c in self.cases(utf8_reference())))
        for before, after in [("len(text.encode('utf-8'))", 'len(text)'),
                              ('isinstance(byte_flag, bool)', 'isinstance(byte_flag, (bool, int))'),
                              ('if byte_flag:', 'if True:')]:
            with self.subTest(mutation=after):
                self.assertTrue(any(not c['passed'] for c in self.cases(utf8_reference().replace(before, after))))
